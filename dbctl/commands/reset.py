"""dbctl reset - drop the branch database and recreate it from the template.

A single confirmation up front; afterwards it is drop (if present) followed
by create with --use, so the fresh database ends up being served.
"""

from __future__ import annotations

from collections.abc import Callable

from dbctl.commands import create, dry, target_db
from dbctl.config import Config
from dbctl.errors import UserAbort
from dbctl.filestore import remove as filestore_remove
from dbctl.postgres import database_exists, drop_database
from dbctl.strategies import get_strategy


def run(cfg: Config, *, yes: bool = False, ask: Callable[[str], bool] | None = None) -> dict:
    branch, db = target_db(cfg)
    if not yes:
        if ask is None:
            raise UserAbort("confirmation required (pass --yes to skip)")
        source_desc = (
            f"'{cfg.postgres.template_db}'" if cfg.postgres.template_db else "scratch (fresh)"
        )
        if not ask(f"reset database '{db}'? It will be dropped and recreated from {source_desc}."):
            raise UserAbort("aborted by user")

    if database_exists(cfg, db) or dry():
        strategy = get_strategy(cfg)
        if strategy.current_database() == db:
            strategy.stop()
            strategy.unuse()
        drop_database(cfg, db)
        filestore_remove(cfg, db)

    result = create.run(cfg, use=True)
    return {"db": db, "source": result["source"], "seeds": result["seeds"]}
