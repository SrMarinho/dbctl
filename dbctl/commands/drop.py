"""dbctl drop - remove a branch database and its filestore, prefix-guarded."""

from __future__ import annotations

from collections.abc import Callable

from dbctl.commands import dry, target_db
from dbctl.config import Config
from dbctl.errors import DatabaseError, UserAbort
from dbctl.filestore import remove as filestore_remove
from dbctl.postgres import database_exists, drop_database
from dbctl.strategies import get_strategy


def run(
    cfg: Config,
    *,
    yes: bool = False,
    db: str | None = None,
    ask: Callable[[str], bool] | None = None,
) -> dict:
    if db is None:
        _, db = target_db(cfg)

    # Refuse anything outside the prefix, even via --db. The same check
    # exists inside postgres.drop_database as the last line of defense.
    if not db.startswith(cfg.postgres.db_prefix):
        raise DatabaseError(
            f"refusing to drop '{db}': it does not start with db_prefix "
            f"'{cfg.postgres.db_prefix}'. dbctl only manages databases it created."
        )

    if not yes:
        if ask is None:
            raise UserAbort("confirmation required (pass --yes to skip)")
        if not ask(f"drop database '{db}' (and its filestore)?"):
            raise UserAbort("aborted by user")

    strategy = get_strategy(cfg)
    if strategy.current_database() == db:
        strategy.stop()
        strategy.unuse()  # the served db no longer exists; back to base config

    existed = database_exists(cfg, db) or dry()
    if existed:
        drop_database(cfg, db)
    filestore_remove(cfg, db)
    return {"db": db, "existed": existed}
