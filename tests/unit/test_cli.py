"""CLI-level tests: exit codes, parsing, hooks golden rules.

Regression anchors: V2 (no project -> exit 2), V3 (invalid config ->
exit 3), the post-checkout golden rule (never exits non-zero).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from dbctl.cli import _command_name, app

runner = CliRunner()


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@l"], check=True)
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    return repo


def _invoke(args: list[str], cwd: Path, monkeypatch, tmp_path: Path):
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("DBCTL_LOG_DIR", str(tmp_path / "logs"))
    return runner.invoke(app, args)


# --- _command_name ----------------------------------------------------------


def test_command_name_plain() -> None:
    assert _command_name(["dbctl", "status"]) == "status"


def test_command_name_skips_global_options() -> None:
    assert _command_name(["dbctl", "--config", "x.toml", "hook", "post-checkout"]) == "hook"
    assert _command_name(["dbctl", "-v", "status"]) == "status"
    assert _command_name(["dbctl", "-p", "/proj", "use"]) == "use"


def test_command_name_root_for_version() -> None:
    assert _command_name(["dbctl", "--version"]) == "root"


def test_command_name_hook_subcommand() -> None:
    assert _command_name(["dbctl", "hook", "post-checkout", "a", "b", "c"]) == "hook"


# --- exit codes -------------------------------------------------------------


def test_version_exits_zero(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DBCTL_LOG_DIR", str(tmp_path / "logs"))
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "dbctl" in result.stdout


def test_no_project_exit_2(tmp_path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)  # git repo WITHOUT .dbctl.toml
    result = _invoke(["status"], repo, monkeypatch, tmp_path)
    assert result.exit_code == 2
    assert "no .dbctl.toml" in result.output


def test_outside_git_exit_4(tmp_path, monkeypatch) -> None:
    result = _invoke(["status"], tmp_path, monkeypatch, tmp_path)
    assert result.exit_code == 4
    assert "not inside a git repository" in result.output


def test_invalid_config_exit_3(tmp_path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    (repo / ".dbctl.toml").write_text("[postgres]\n", encoding="utf-8")
    result = _invoke(["status"], repo, monkeypatch, tmp_path)
    assert result.exit_code == 3
    assert "[postgres].user" in result.output


def test_drop_outside_prefix_exit_6(tmp_path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    (repo / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n',
        encoding="utf-8",
    )
    result = _invoke(["drop", "--db", "postgres", "--yes"], repo, monkeypatch, tmp_path)
    assert result.exit_code == 6
    assert "does not start with db_prefix" in result.output


def test_unknown_command_exits_nonzero(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DBCTL_LOG_DIR", str(tmp_path / "logs"))
    result = runner.invoke(app, ["frobnicate"])
    assert result.exit_code != 0


def test_hook_post_checkout_never_fails(tmp_path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)  # NO config at all
    result = _invoke(["hook", "post-checkout", "main", "feature", "1"], repo, monkeypatch, tmp_path)
    # golden rule: the hook runner must exit 0 even with zero config
    assert result.exit_code == 0


def test_status_ok_with_config(tmp_path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    (repo / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n',
        encoding="utf-8",
    )
    # All docker/git calls are real here except psql: status needs the
    # database existence check -> patch the psql channel.
    import dbctl.postgres as pg

    monkeypatch.setattr(pg, "exec_in", lambda *a, **k: "")
    result = _invoke(["status"], repo, monkeypatch, tmp_path)
    assert result.exit_code == 0
    assert "branch:" in result.output
    assert "target db:" in result.output
