"""The ONLY module allowed to spawn subprocesses.

Every docker/git/psql call in the codebase goes through this wrapper so
that logging, error handling and the DBCTL_DRY_RUN mode stay in one place.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

from dbctl import logging as dlog
from dbctl.errors import DockerError


def _is_dry_run() -> bool:
    return os.environ.get("DBCTL_DRY_RUN") == "1"


def _build_env(extra: dict[str, str] | None) -> dict[str, str]:
    env = dict(os.environ)
    if extra:
        env.update(extra)
    return env


def _tail(text: str | None, limit: int = 4000) -> str:
    """Last ``limit`` chars of stderr/stdout for the log (bounded)."""
    if not text:
        return ""
    return text[-limit:]


def _execute(
    cmd: list[str],
    *,
    input: str | None,
    capture: bool,
    env: dict[str, str] | None,
    cwd: str | None,
) -> str:
    redacted = dlog.redact_argv(cmd)
    if _is_dry_run():
        print(f"dry-run: {' '.join(shlex.quote(c) for c in cmd)}")
        dlog.debug("exec_dry_run", argv=redacted, cwd=cwd)
        return ""
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=input,
            capture_output=capture,
            text=True,
            env=_build_env(env),
            cwd=cwd,
        )
    except FileNotFoundError:
        dlog.error(
            "exec_failed",
            argv=redacted,
            cwd=cwd,
            error="binary not found",
        )
        raise DockerError(f"binary not found; cannot run: {' '.join(cmd)}") from None
    duration_ms = int((time.monotonic() - started) * 1000)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        if not detail and not capture:
            detail = "(output was streamed to the terminal above)"
        dlog.error(
            "exec_failed",
            argv=redacted,
            cwd=cwd,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            output_tail=_tail(detail),
        )
        raise DockerError(f"command failed (exit {proc.returncode}): {' '.join(cmd)}\n{detail}")
    dlog.debug("exec_ok", argv=redacted, cwd=cwd, exit_code=0, duration_ms=duration_ms)
    return (proc.stdout or "").strip() if capture else ""


def run(
    args: list[str],
    *,
    input: str | None = None,
    capture: bool = False,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> str:
    """Run an arbitrary command (git, psql on the host, etc.)."""
    return _execute(args, input=input, capture=capture, env=env, cwd=cwd)


def exec_in(
    container: str,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    input: str | None = None,
    capture: bool = False,
) -> str:
    """Run ``args`` inside ``container`` via `docker exec`.

    ``env`` entries are passed with `-e`: they travel through the Docker
    API (e.g. PGPASSWORD), never through the host command line.
    """
    cmd: list[str] = ["docker", "exec"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    if input is not None:
        cmd.append("-i")
    cmd += [container] + list(args)
    return _execute(cmd, input=input, capture=capture, env=None, cwd=None)


def compose(
    project_root: Path,
    compose_files: Iterable[str],
    args: list[str],
    *,
    input: str | None = None,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    """Run a `docker compose` command for ``project_root``."""
    cmd: list[str] = ["docker", "compose"]
    for f in compose_files:
        cmd += ["-f", f]
    cmd += list(args)
    return _execute(cmd, input=input, capture=capture, env=env, cwd=str(project_root))


def container_running(name: str) -> bool:
    """Whether a container with ``name`` exists and is running."""
    try:
        out = run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture=True,
        )
        return out.strip() == "true"
    except DockerError:
        return False
