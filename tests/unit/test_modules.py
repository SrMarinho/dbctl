"""Unit tests for dbctl.modules: glob translation, module_of, detection.

Detection runs against a real tiny git repo (no Docker): the git plumbing
(merge-base, changed paths) is exercised for real.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from dbctl.config import Config, load_config
from dbctl.modules import _glob_to_regex, _ignored, detect, module_of


def test_glob_to_regex_double_star() -> None:
    rx = _glob_to_regex("**/x")
    assert rx.match("x")
    assert rx.match("a/b/x")
    assert not rx.match("a/b/y")


def test_glob_to_regex_single_star_stays_in_segment() -> None:
    rx = _glob_to_regex("*.md")
    assert rx.match("README.md")
    assert not rx.match("docs/README.md")


def test_glob_to_regex_question_mark() -> None:
    rx = _glob_to_regex("file?.txt")
    assert rx.match("file1.txt")
    assert not rx.match("file12.txt")


def test_ignored_matches_any_pattern() -> None:
    assert _ignored("docs/x.md", ["docs/**", "*.lock"])
    assert _ignored("poetry.lock", ["docs/**", "*.lock"])
    assert not _ignored("src/app.py", ["docs/**", "*.lock"])


def test_module_of_walks_up(tmp_path) -> None:
    root = tmp_path / "repo"
    manifest = root / "addons" / "sale" / "__manifest__.py"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    path = "addons/sale/models/sale_order.py"
    assert module_of(path, root, "__manifest__.py") == "sale"


def test_module_of_none_outside_module(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docker-compose.yml").write_text("x", encoding="utf-8")
    assert module_of("docker-compose.yml", root, "__manifest__.py") is None


def _repo_with_modules(tmp_path) -> Path:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-b", "main", "-q"],):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@l"], check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feature"], check=True)
    return repo


def _cfg_for(repo: Path) -> Config:
    toml = repo / ".dbctl.toml"
    toml.write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n',
        encoding="utf-8",
    )
    return load_config(repo, toml)


def test_detect_finds_changed_modules(tmp_path) -> None:
    repo = _repo_with_modules(tmp_path)
    module_dir = repo / "addons" / "demo"
    module_dir.mkdir(parents=True)
    (module_dir / "__manifest__.py").write_text("{}", encoding="utf-8")
    (module_dir / "models").mkdir()
    (module_dir / "models" / "x.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "demo"], check=True)

    result = detect(_cfg_for(repo))
    assert result["modules"] == ["demo"]
    assert "addons/demo/models/x.py" in result["changed_paths"]


def test_detect_ignores_configured_globs(tmp_path) -> None:
    repo = _repo_with_modules(tmp_path)
    toml = repo / ".dbctl.toml"
    toml.write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n'
        '[modules]\nignore = ["docs/**"]\n',
        encoding="utf-8",
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("doc\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "docs"], check=True)

    result = detect(load_config(repo, toml))
    assert result["modules"] == []
    assert "docs/guide.md" not in result["changed_paths"]


def test_detect_unmatched_files_reported(tmp_path) -> None:
    repo = _repo_with_modules(tmp_path)
    (repo / "docker-compose.yml").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "compose"], check=True)

    result = detect(_cfg_for(repo))
    assert result["modules"] == []
    assert "docker-compose.yml" in result["unmatched"]


def test_detect_detects_new_untracked_module(tmp_path) -> None:
    repo = _repo_with_modules(tmp_path)
    fresh = repo / "addons" / "fresh"
    fresh.mkdir(parents=True)
    (fresh / "__manifest__.py").write_text("{}", encoding="utf-8")

    result = detect(_cfg_for(repo))
    assert result["modules"] == ["fresh"]
