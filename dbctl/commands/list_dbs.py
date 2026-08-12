"""dbctl list - show the branch databases of this project's prefix."""

from __future__ import annotations

from dbctl.config import Config
from dbctl.errors import GitError
from dbctl.naming import database_name
from dbctl.postgres import list_databases
from dbctl.project import current_branch
from dbctl.strategies import get_strategy


def run(cfg: Config) -> dict:
    rows = list_databases(cfg, cfg.postgres.db_prefix)
    served = get_strategy(cfg).current_database()
    current: str | None = None
    try:
        current = database_name(current_branch(cfg.project_root), cfg.postgres.db_prefix)
    except GitError:
        pass  # listing works even without a usable branch
    return {"rows": rows, "current": current, "served": served}
