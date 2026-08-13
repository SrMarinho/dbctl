"""Unit tests for dbctl.logging: JSONL schema, redaction, log_dir."""

from __future__ import annotations

import json
from pathlib import Path

from dbctl import logging as dlog
from dbctl.logging import log_dir, redact_argv


def test_redact_argv_masks_docker_env_flags() -> None:
    argv = ["exec", "-e", "PGPASSWORD=hunter2", "psql", "-c", "x"]
    assert redact_argv(argv) == ["exec", "-e", "PGPASSWORD=***", "psql", "-c", "x"]


def test_redact_argv_combined_flag() -> None:
    argv = ["-e PGPASSWORD=secret", "psql"]
    assert redact_argv(argv) == ["-e PGPASSWORD=***", "psql"]


def test_redact_argv_leaves_plain_args() -> None:
    argv = ["status", "--verbose", "-d", "dev_x"]
    assert redact_argv(argv) == argv


def test_redact_argv_keeps_key_without_value() -> None:
    assert redact_argv(["-e", "PGPASSWORD"]) == ["-e", "PGPASSWORD"]


def test_log_dir_defaults_to_tool_repo_logs(monkeypatch) -> None:
    monkeypatch.delenv("DBCTL_LOG_DIR", raising=False)
    expected = Path(__file__).resolve().parent.parent.parent / "logs"
    assert log_dir() == expected


def test_log_dir_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DBCTL_LOG_DIR", str(tmp_path / "custom"))
    assert log_dir() == tmp_path / "custom"


def test_log_writes_jsonl_with_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DBCTL_LOG_DIR", str(tmp_path))
    path = dlog.init("status", project_root="/tmp/x")
    assert path is not None and path.exists()
    dlog.set_context(config="/tmp/x/.dbctl.toml")
    dlog.info("exec_ok", argv=["git", "status"], exit_code=0)
    line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "exec_ok"
    assert record["level"] == "info"
    assert record["command"] == "status"
    assert record["project_root"] == "/tmp/x"
    assert record["config"] == "/tmp/x/.dbctl.toml"
    assert record["argv"] == ["git", "status"]
    assert record["exit_code"] == 0
    assert record["ts"].endswith("+00:00") or "+00:00" in record["ts"]


def test_log_level_fallback_for_unknown_level(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DBCTL_LOG_DIR", str(tmp_path))
    dlog.init("x")
    dlog.log("nope", "some_event")
    line = tmp_path.glob("dbctl-*.jsonl").__next__().read_text(encoding="utf-8").strip()
    assert json.loads(line.splitlines()[-1])["level"] == "info"
