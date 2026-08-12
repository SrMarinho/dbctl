"""Command orchestration. Each module implements one use case and returns
plain data for the CLI to format. No printing, no business-rule leaks into
cli.py."""

from __future__ import annotations

from dbctl.config import Config
from dbctl.naming import database_name
from dbctl.project import current_branch


def target_db(cfg: Config) -> tuple[str, str]:
    """(branch, database name) for the current branch of the project."""
    branch = current_branch(cfg.project_root)
    return branch, database_name(branch, cfg.postgres.db_prefix)
