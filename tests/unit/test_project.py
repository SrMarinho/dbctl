"""Unit tests for dbctl.project: discovery (spec 5.0) and git helpers.

Uses REAL git repos in tmp dirs (no Docker needed): project.py only spawns
git, which is present in any dev environment.
"""

from __future__ import annotations

import pytest

from dbctl.errors import ConfigError, GitError, ProjectNotFoundError
from dbctl.project import (
    changed_paths,
    current_branch,
    default_base_ref,
    find_config,
    hooks_dir,
    is_git_repo,
    merge_base,
    project_root,
    working_tree_dirty,
)


def _write_config(repo, sub: str = "") -> None:
    target = repo / sub
    target.mkdir(parents=True, exist_ok=True)
    (target / ".dbctl.toml").write_text("[postgres]\n", encoding="utf-8")


def test_project_root_from_deep_subdir(git_repo) -> None:
    deep = git_repo / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert project_root(deep) == git_repo


def test_project_root_raises_outside_git(tmp_path) -> None:
    with pytest.raises(GitError, match="not inside a git repository"):
        project_root(tmp_path)


def test_find_config_walks_up(git_repo) -> None:
    _write_config(git_repo)
    deep = git_repo / "a" / "b"
    deep.mkdir(parents=True)
    cfg, root = find_config(deep)
    assert cfg == (git_repo / ".dbctl.toml").resolve()
    assert root == git_repo


def test_find_config_walks_down_from_top(git_repo) -> None:
    _write_config(git_repo, "temp/seeds")
    cfg, root = find_config(git_repo)
    assert cfg == (git_repo / "temp" / "seeds" / ".dbctl.toml").resolve()


def test_find_config_none_raises_project_not_found(git_repo) -> None:
    with pytest.raises(ProjectNotFoundError, match="no .dbctl.toml"):
        find_config(git_repo)


def test_find_config_ambiguous_raises(git_repo) -> None:
    _write_config(git_repo)
    _write_config(git_repo, "temp")
    with pytest.raises(ConfigError, match="more than one"):
        find_config(git_repo)


def test_find_config_explicit_skips_search(git_repo, tmp_path) -> None:
    _write_config(git_repo, "elsewhere")
    explicit = git_repo / "elsewhere" / ".dbctl.toml"
    cfg, root = find_config(git_repo, explicit=explicit)
    assert cfg == explicit.resolve()


def test_find_config_explicit_missing(git_repo) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        find_config(git_repo, explicit=git_repo / "nope.toml")


def test_current_branch(git_repo) -> None:
    assert current_branch(git_repo) == "feature"


def test_current_branch_detached_raises(git_repo) -> None:
    import subprocess

    subprocess.run(["git", "-C", str(git_repo), "checkout", "-q", "--detach"], check=True)
    with pytest.raises(GitError, match="detached"):
        current_branch(git_repo)


def test_is_git_repo(git_repo, tmp_path) -> None:
    assert is_git_repo(git_repo) is True
    assert is_git_repo(tmp_path / "nope") is False


def test_working_tree_dirty(git_repo) -> None:
    assert working_tree_dirty(git_repo) is False
    (git_repo / "dirty.txt").write_text("x", encoding="utf-8")
    assert working_tree_dirty(git_repo) is True


def test_hooks_dir_default(git_repo) -> None:
    assert hooks_dir(git_repo) == git_repo / ".git" / "hooks"


def test_hooks_dir_respects_custom_path(git_repo) -> None:
    import subprocess

    custom = git_repo / "custom-hooks"
    custom.mkdir()
    subprocess.run(
        ["git", "-C", str(git_repo), "config", "core.hooksPath", "custom-hooks"], check=True
    )
    assert hooks_dir(git_repo) == git_repo / "custom-hooks"


def test_default_base_ref_configured_wins(git_repo) -> None:
    assert default_base_ref(git_repo, "origin/develop") == "origin/develop"


def test_default_base_ref_falls_back_to_local_main(git_repo) -> None:
    # No origin/HEAD in a local-only repo -> main (or master/develop).
    ref = default_base_ref(git_repo)
    assert ref in ("main", "master", "develop")


def test_default_base_ref_none_raises(tmp_path) -> None:
    import subprocess

    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@l"], check=True)
    with pytest.raises(ConfigError, match="base_ref"):
        default_base_ref(repo)


def test_merge_base_and_changed_paths(git_repo) -> None:
    import subprocess

    (git_repo / "addons" / "demo" / "__manifest__.py").parent.mkdir(parents=True)
    (git_repo / "addons" / "demo" / "__manifest__.py").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(git_repo), "commit", "-qm", "demo module"], check=True)

    base = merge_base(git_repo, "main")
    assert base
    paths = changed_paths(git_repo, base)
    assert "addons/demo/__manifest__.py" in paths
    # Untracked files are reported too (brand-new module before first commit).
    (git_repo / "addons" / "fresh" / "__manifest__.py").parent.mkdir(parents=True)
    (git_repo / "addons" / "fresh" / "__manifest__.py").write_text("{}", encoding="utf-8")
    paths = changed_paths(git_repo, base)
    assert "addons/fresh/__manifest__.py" in paths
