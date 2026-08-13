"""Integration tests: run the real dbctl CLI against the dbctl-sandbox.

These tests need Docker with the sandbox project (postgres + odoo containers)
up. They skip cleanly when the environment is unavailable, so the default
`pytest tests` run stays green on any machine.

The create/use/drop cycle runs on a THROWAWAY branch (test-integration-*);
the sandbox's original branch is restored and the throwaway database is
dropped in a finally block, so the sandbox is left exactly as it was found.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

SANDBOX = Path(os.environ.get("DBCTL_TEST_SANDBOX", "~/projects/dbctl-sandbox")).expanduser()
DBCTL = Path(os.environ.get("DBCTL_BIN", "~/projects/dbctl/.venv/bin/dbctl")).expanduser()

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=15)
        return proc.returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="module")
def sandbox() -> Path:
    ready = (
        _docker_available()
        and SANDBOX.is_dir()
        and (SANDBOX / ".dbctl.toml").is_file()
        and DBCTL.is_file()
    )
    if not ready:
        pytest.skip(
            f"integration environment unavailable: docker daemon, {SANDBOX} or {DBCTL} missing"
        )
    return SANDBOX


def _git(sandbox: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(sandbox), *args], capture_output=True, text=True)


def _dbctl(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(DBCTL), *args], cwd=str(cwd), capture_output=True, text=True, timeout=600
    )


def test_status_read_only(sandbox: Path) -> None:
    result = _dbctl("status", cwd=sandbox)
    assert result.returncode == 0, result.stderr
    assert "project:" in result.stdout
    assert "branch:" in result.stdout
    assert "target db:" in result.stdout


def test_list_read_only(sandbox: Path) -> None:
    result = _dbctl("list", cwd=sandbox)
    assert result.returncode == 0, result.stderr
    assert "DATABASE" in result.stdout or "no databases" in result.stdout


def test_create_use_upgrade_drop_cycle(sandbox: Path) -> None:
    original_branch = _git(sandbox, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    test_branch = f"test-integration-{uuid.uuid4().hex[:8]}"
    _git(sandbox, "checkout", "-qb", test_branch)
    try:
        result = _dbctl("create", "--use", cwd=sandbox)
        assert result.returncode == 0, result.stderr
        assert "created dev_" in result.stdout

        status = _dbctl("status", cwd=sandbox)
        assert status.returncode == 0, status.stderr
        assert "exists:      yes" in status.stdout

        upgrade = _dbctl("upgrade", "-m", "base", cwd=sandbox)
        assert upgrade.returncode == 0, upgrade.stderr

        served = _dbctl("status", cwd=sandbox)
        assert served.returncode == 0, served.stderr
        from dbctl.naming import database_name

        target = database_name(test_branch, "dev_")
        assert f"served now:  {target}" in served.stdout
    finally:
        # Drop the throwaway database first (still on the test branch), then
        # restore the sandbox's original branch. Both are best-effort.
        _dbctl("drop", "--yes", cwd=sandbox)
        _git(sandbox, "checkout", "-q", original_branch)
        assert _git(sandbox, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == original_branch
