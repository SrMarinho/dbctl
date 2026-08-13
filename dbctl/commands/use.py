"""dbctl use - point the Odoo service at the branch database."""

from __future__ import annotations

from dbctl.commands import dry, target_db
from dbctl.config import Config
from dbctl.errors import DatabaseError
from dbctl.postgres import database_exists
from dbctl.strategies import get_strategy


def run(cfg: Config) -> dict:
    branch, db = target_db(cfg)
    if not dry() and not database_exists(cfg, db):
        raise DatabaseError(
            f"database '{db}' does not exist - run 'dbctl create' first (branch '{branch}')."
        )
    get_strategy(cfg).start(db)
    return {"db": db}
