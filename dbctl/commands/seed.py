"""dbctl seed - run base.py and the branch's seed file, if any."""

from __future__ import annotations

from dbctl.commands import dry, target_db
from dbctl.config import Config
from dbctl.errors import DatabaseError
from dbctl.postgres import database_exists
from dbctl.seeding import run_seeds


def run(cfg: Config) -> dict:
    branch, db = target_db(cfg)
    if not dry() and not database_exists(cfg, db):
        raise DatabaseError(
            f"database '{db}' does not exist - run 'dbctl create' first "
            f"(branch '{branch}')."
        )
    if cfg.seeds.path is None or not cfg.seeds.path.is_dir():
        return {"skipped": True}
    ran = run_seeds(cfg, db, branch)
    return {"ran": ran}
