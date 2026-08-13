"""Unit tests for seeding (ephemeral odoo shell channel) and sanitize."""

from __future__ import annotations

import pytest

from dbctl.errors import DatabaseError, SeedError
from dbctl.filestore import copy as filestore_copy
from dbctl.filestore import remove as filestore_remove
from dbctl.sanitize import sanitize
from dbctl.seeding import run_python, run_seeds


def test_run_python_builds_compose_command(make_config, fake_compose) -> None:
    fake_compose.default = "output"
    out = run_python(make_config(), "dev_x", "print(1)")
    assert out == "output"
    cmd = fake_compose.last()
    joined = " ".join(cmd)
    assert "run" in cmd and "--rm" in cmd and "--no-deps" in cmd
    assert "web" in cmd and "odoo" in cmd and "shell" in cmd
    assert "-d" in cmd and "dev_x" in cmd and "--no-http" in cmd
    assert joined.startswith("docker-compose.yml ")


def test_run_python_adds_volumes(make_config, fake_compose) -> None:
    run_python(make_config(), "dev_x", "x", extra_volumes=["/a:/b"])
    cmd = fake_compose.last()
    assert "-v" in cmd and "/a:/b" in cmd


def test_run_python_wraps_failure_as_seed_error(make_config, fake_compose) -> None:

    fake_compose.fail_on("shell", exit_code=1)
    with pytest.raises(SeedError, match="odoo shell failed"):
        run_python(make_config(), "dev_x", "x")


def test_run_seeds_no_dir_returns_empty(make_config, tmp_path) -> None:
    cfg = make_config()  # seeds not configured at all
    assert run_seeds(cfg, "dev_x", "feature") == []


def test_run_seeds_mounts_dir_and_parses_markers(make_config, tmp_path, fake_compose) -> None:
    seeds = tmp_path / "temp" / "seeds"
    (seeds / "branches").mkdir(parents=True)
    (seeds / "base.py").write_text("x", encoding="utf-8")
    (seeds / "branches" / "feature-x.py").write_text("y", encoding="utf-8")
    cfg = make_config('[seeds]\npath = "temp/seeds"\n')
    fake_compose.default = (
        "DBCTL_SEED_RAN:/mnt/dbctl-seeds/base.py\n"
        "DBCTL_SEED_RAN:/mnt/dbctl-seeds/branches/feature-x.py\n"
    )
    ran = run_seeds(cfg, "dev_x", "feature-x")
    assert len(ran) == 2
    assert ran[0].endswith("base.py")
    # volume must be passed explicitly (independent of the override)
    cmd = fake_compose.last()
    assert any(f"{cfg.seeds.path}:{cfg.seeds.mount}" in a for a in cmd)


def test_run_seeds_branch_slug_used(make_config, tmp_path, fake_compose) -> None:
    seeds = tmp_path / "temp" / "seeds"
    (seeds / "branches").mkdir(parents=True)
    (seeds / "base.py").write_text("x", encoding="utf-8")
    cfg = make_config('[seeds]\npath = "temp/seeds"\n')
    fake_compose.default = ""
    run_seeds(cfg, "dev_x", "Feature X")
    # the bootstrap (piped as stdin) references branches/feature_x.py (slugified)
    assert fake_compose.inputs and "feature_x" in fake_compose.inputs[-1]
    assert "branches" in fake_compose.inputs[-1]


def test_sanitize_runs_python_via_seeding_channel(make_config, monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_run_python(cfg, db, code, **kwargs):  # noqa: ANN001
        calls.append((db, code, kwargs.get("purpose")))
        return "DBCTL_SANITIZED"

    monkeypatch.setattr("dbctl.sanitize.run_python", fake_run_python)
    sanitize(make_config(), "dev_x")
    db, code, purpose = calls[0]
    assert db == "dev_x"
    assert purpose == "sanitize"
    assert "database.uuid" in code
    assert "ir.mail_server" in code
    assert "ir.cron" not in code.replace("ir.cron is NOT", "") or "ir.cron" in code


def test_filestore_copy_missing(make_config, fake_compose) -> None:
    fake_compose.on("DBCTL_FILESTORE_MISSING", returns="DBCTL_FILESTORE_MISSING")
    assert filestore_copy(make_config(), "tpl", "dev_x") == "missing"


def test_filestore_copy_copied(make_config, fake_compose) -> None:
    fake_compose.on("DBCTL_FILESTORE_COPIED", returns="DBCTL_FILESTORE_COPIED")
    assert filestore_copy(make_config(), "tpl", "dev_x") == "copied"
    cmd = fake_compose.last()
    joined = " ".join(cmd)
    assert "/var/lib/odoo/filestore/tpl" in joined
    assert "/var/lib/odoo/filestore/dev_x" in joined


def test_filestore_remove_prefix_guard(make_config) -> None:
    with pytest.raises(DatabaseError, match="does not start with"):
        filestore_remove(make_config(), "other_db")


def test_filestore_remove_builds_rm(make_config, fake_compose) -> None:
    filestore_remove(make_config(), "dev_x")
    joined = " ".join(fake_compose.last())
    assert 'rm -rf "/var/lib/odoo/filestore/dev_x"' in joined
