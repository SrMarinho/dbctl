"""JSONL structured logging — machine-readable logs for agent loops.

Every invocation appends one JSON object per line to a per-day file:

    <log_dir>/dbctl-YYYY-MM-DD.jsonl

log_dir resolution: DBCTL_LOG_DIR (env) -> <dbctl repo>/logs ->
~/.dbctl/logs (fallback). The `logs/` folder is gitignored.

Why structured (JSONL) instead of plain text: a fixed flat schema means a
reading model (or jq) can consume events with no parsing ambiguity —
timestamps are ISO-8601 UTC, every line carries the run id, command, level
and context fields. The console (typer output) is the human channel; this
file is the diagnostic channel.

Flat schema, snake_case: ts, run, level, event, command, then context and
per-event fields. Secrets are redacted before anything is written
(redact_argv masks `-e KEY=value` docker exec flags).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_FILE = None
_PATH: Path | None = None
_RUN_ID = ""
_COMMAND = ""
_CONTEXT: dict = {}

_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


def _repo_dir() -> Path:
    """Root of the dbctl repository (dbctl/logging.py -> parent.parent)."""
    return Path(__file__).resolve().parent.parent


def log_dir() -> Path:
    override = os.environ.get("DBCTL_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return _repo_dir() / "logs"


def init(command: str, **fields) -> Path | None:
    """Open the per-day file and record the invocation. Returns the path."""
    global _FILE, _PATH, _RUN_ID, _COMMAND, _CONTEXT
    _COMMAND = command
    _RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3]
    _CONTEXT = {}
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"dbctl-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        _FILE = open(path, "a", encoding="utf-8")
        _PATH = path
    except OSError:
        _FILE = None
        _PATH = None
    _CONTEXT.update(fields)
    log(
        "info",
        "invocation",
        argv=redact_argv(sys.argv[1:]),
        cwd=str(Path.cwd()),
        pid=os.getpid(),
    )
    return _PATH


def set_context(**fields) -> None:
    """Merge persistent per-run fields (project_root, config, ...)."""
    _CONTEXT.update(fields)


def redact_argv(argv: list[str]) -> list[str]:
    """Mask secret-looking flags: `-e KEY=value` (docker exec env) -> KEY=***."""
    redacted: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-e" and i + 1 < len(argv) and "=" in argv[i + 1]:
            key = argv[i + 1].split("=", 1)[0]
            redacted += ["-e", f"{key}=***"]
            i += 2
            continue
        if arg.startswith("-e ") and "=" in arg:
            key = arg.split("=", 1)[0]
            redacted.append(f"{key}=***")
        else:
            redacted.append(arg)
        i += 1
    return redacted


def _clean(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {key: _clean(v) for key, v in value.items()}
    return value


def log(level: str, event: str, **fields) -> None:
    record: dict = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "run": _RUN_ID,
        "level": level if level in _LEVELS else "info",
        "event": event,
        "command": _COMMAND,
    }
    record.update(_CONTEXT)
    record.update({key: _clean(value) for key, value in fields.items()})
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _LOCK:
        if _FILE is not None:
            try:
                _FILE.write(line)
                _FILE.flush()
            except OSError:
                pass


def debug(event: str, **fields) -> None:
    log("debug", event, **fields)


def info(event: str, **fields) -> None:
    log("info", event, **fields)


def warning(event: str, **fields) -> None:
    log("warning", event, **fields)


def error(event: str, **fields) -> None:
    log("error", event, **fields)


def log_exception(event: str = "command_crashed", **fields) -> None:
    fields.setdefault("error_type", "Exception")
    fields["traceback"] = traceback.format_exc().strip()
    log("error", event, **fields)
