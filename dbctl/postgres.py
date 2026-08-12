"""Postgres operations.

Everything runs through `docker exec` in the Postgres container - never
through a host psql client. PGPASSWORD travels via exec env (Docker API),
not the host command line.
"""

from __future__ import annotations

import os

from dbctl.config import Config
from dbctl.docker import exec_in
from dbctl.errors import DatabaseError


def _is_dry_run() -> bool:
    return os.environ.get("DBCTL_DRY_RUN") == "1"


def _ident(name: str) -> str:
    """Quote a name as an SQL identifier (CREATE/DROP DATABASE ...)."""
    return '"' + name.replace('"', '""') + '"'


def _lit(name: str) -> str:
    """Quote a name as an SQL string literal (datname = ...)."""
    return "'" + name.replace("'", "''") + "'"


def _psql(cfg: Config, sql: str, *, capture: bool = True) -> str:
    env = {"PGPASSWORD": cfg.postgres.password}
    return exec_in(
        cfg.postgres.container,
        ["psql", "-U", cfg.postgres.user, "-d", "postgres", "-tA", "-c", sql],
        env=env,
        capture=capture,
    )


def database_exists(cfg: Config, name: str) -> bool:
    if _is_dry_run():
        # In dry-run every command prints and returns nothing; assume the
        # database exists so the flow can walk through all the steps.
        return True
    out = _psql(cfg, f"SELECT 1 FROM pg_database WHERE datname = {_lit(name)}")
    return out.strip() == "1"


def list_databases(cfg: Config, prefix: str) -> list[tuple[str, str]]:
    """(name, human-readable size) for every database starting with ``prefix``."""
    # Escape LIKE metacharacters so '_' in the prefix is literal.
    pattern = (
        prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )
    out = _psql(
        cfg,
        "SELECT datname, pg_size_pretty(pg_database_size(datname)) "
        "FROM pg_database WHERE datname LIKE "
        f"{_lit(pattern)} ESCAPE '\\' ORDER BY datname",
    )
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if "|" in line:
            name, _, size = line.partition("|")
            rows.append((name.strip(), size.strip()))
    return rows


def terminate_connections(cfg: Config, name: str) -> None:
    _psql(
        cfg,
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = {_lit(name)} AND pid <> pg_backend_pid()",
    )


def clone_database(cfg: Config, source: str, target: str) -> None:
    if not _is_dry_run() and database_exists(cfg, target):
        raise DatabaseError(
            f"database '{target}' already exists - use 'dbctl reset' to recreate it "
            "from the template."
        )
    try:
        _psql(cfg, f"CREATE DATABASE {_ident(target)} TEMPLATE {_ident(source)}")
    except Exception as exc:
        raise DatabaseError(
            f"failed to clone '{source}' -> '{target}': {exc}"
        ) from exc


def drop_database(cfg: Config, name: str) -> None:
    """Drop ``name`` and its filestore. Refuses anything without the prefix.

    This check lives HERE, at the last line of defense, in addition to the
    command layer: no caller can drop a database outside the prefix.
    """
    prefix = cfg.postgres.db_prefix
    if not name.startswith(prefix):
        raise DatabaseError(
            f"refusing to drop '{name}': it does not start with db_prefix "
            f"'{prefix}'. dbctl only manages databases it created."
        )
    terminate_connections(cfg, name)
    _psql(cfg, f'DROP DATABASE IF EXISTS {_ident(name)}')
