"""Shared fixtures for the dbctl test suite.

Unit tests never touch Docker: every process boundary (git via
``dbctl.docker.run``, psql via ``dbctl.postgres.exec_in``, compose) is
patched with scripted fakes matching the real signatures. Integration tests
(tests/integration) run against a real Docker daemon and the dbctl-sandbox
project, and skip when they are unavailable.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from dbctl.config import Config, load_config

TOML_MIN = """\
[postgres]
container = "pg-test"
user = "tester"
password = "secret"
template_db = "tpl"
db_prefix = "dev_"

[odoo]
container = "odoo-test"
compose_service = "web"
"""


class FakeProc:
    """Records flat argv lists; scripts responses / failures by substring."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []
        self.responses: dict[tuple, str] = {}
        self.default = ""
        self.fail_patterns: list[tuple[str, int, str | None]] = []

    def _check(self, parts: list[str]) -> str:
        for pattern, code, message in self.fail_patterns:
            if any(pattern in p for p in parts):
                from dbctl.errors import DockerError

                detail = message or f"command failed (exit {code})"
                raise DockerError(f"{detail}: {' '.join(parts)}")
        for key, value in self.responses.items():
            if all(any(k in p for p in parts) for k in key):
                return value
        return self.default

    def on(self, *substrings: str, returns: str) -> None:
        self.responses[substrings] = returns

    def fail_on(self, *substrings: str, exit_code: int = 1, message: str | None = None) -> None:
        for s in substrings:
            self.fail_patterns.append((s, exit_code, message))

    def last(self) -> list[str]:
        return self.calls[-1]


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> FakeProc:
    """Patch `dbctl.project.run` (every git call) and the branch name."""

    fake = FakeProc()

    def run(args: list[str], **kwargs: object) -> str:
        parts = list(args)
        out = fake._check(parts)
        fake.calls.append(parts)
        return out

    monkeypatch.setattr("dbctl.project.run", run)
    monkeypatch.setattr("dbctl.commands.current_branch", lambda root: "feature-x")
    return fake


@pytest.fixture
def fake_psql(monkeypatch: pytest.MonkeyPatch) -> FakeProc:
    """Patch `dbctl.postgres.exec_in` (the `docker exec psql` channel)."""

    fake = FakeProc()

    def exec_in(container: str, args: list[str], **kwargs: object) -> str:
        parts = [container] + list(args)
        out = fake._check(parts)
        fake.calls.append(parts)
        return out

    monkeypatch.setattr("dbctl.postgres.exec_in", exec_in)
    return fake


@pytest.fixture
def fake_compose(monkeypatch: pytest.MonkeyPatch) -> FakeProc:
    """Patch every `docker compose` call site (strategy/seeding/filestore/cli)."""

    fake = FakeProc()

    def compose(
        project_root: Path, compose_files: list[str], args: list[str], **kwargs: object
    ) -> str:
        parts = list(compose_files) + list(args)
        out = fake._check(parts)
        fake.calls.append(parts)
        fake.inputs.append(kwargs.get("input"))
        return out

    for target in (
        "dbctl.strategies.compose_override.compose",
        "dbctl.seeding.compose",
        "dbctl.filestore.compose",
        "dbctl.cli.compose",
    ):
        monkeypatch.setattr(target, compose)
    return fake


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp dir containing a valid .dbctl.toml (env log dir redirected)."""
    monkeypatch.setenv("DBCTL_LOG_DIR", str(tmp_path / "logs"))
    (tmp_path / ".dbctl.toml").write_text(TOML_MIN, encoding="utf-8")
    return tmp_path


@pytest.fixture
def make_config(tmp_path: Path) -> Callable:
    """Build a Config from ``tmp_path`` plus optional TOML extra sections."""

    def _make(extra: str = "", *, root: Path | None = None, config: str | None = None) -> Config:
        base = root or tmp_path
        cfg_path = Path(config) if config else base / ".dbctl.toml"
        cfg_path.write_text(TOML_MIN + extra, encoding="utf-8")
        return load_config(base, cfg_path)

    return _make


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A real (tiny) git repository with main + feature branches."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main", "-q")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "config", "user.email", "tester@local")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feature")
    return repo


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {args} failed: {proc.stderr}")
    return proc.stdout.strip()
