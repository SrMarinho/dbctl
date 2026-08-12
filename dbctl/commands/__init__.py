"""Command orchestration. Each module implements one use case and returns
plain data for the CLI to format. No printing, no business-rule leaks into
cli.py."""

from __future__ import annotations

import os

from dbctl.config import Config
from dbctl.naming import database_name
from dbctl.project import current_branch


def dry() -> bool:
    """True when DBCTL_DRY_RUN is set: print commands, skip side effects."""
    return os.environ.get("DBCTL_DRY_RUN") == "1"


def target_db(cfg: Config) -> tuple[str, str]:
    """(branch, database name) for the current branch of the project."""
    branch = current_branch(cfg.project_root)
    return branch, database_name(branch, cfg.postgres.db_prefix)
