"""dbctl create - clone the template into the branch database."""

from __future__ import annotations

from dbctl.commands import target_db
from dbctl.config import Config
from dbctl.errors import DatabaseError
from dbctl.filestore import copy as filestore_copy
from dbctl.postgres import (
    clone_database,
    database_exists,
    drop_database,
    terminate_connections,
)
from dbctl.sanitize import sanitize
from dbctl.seeding import run_seeds
from dbctl.strategies import get_strategy


def run(
    cfg: Config,
    *,
    template: str | None = None,
    no_seed: bool = False,
    use: bool = False,
) -> dict:
    branch, db = target_db(cfg)
    if database_exists(cfg, db):
        raise DatabaseError(
            f"database '{db}' already exists - use 'dbctl reset' to recreate it "
            "from the template."
        )
    source = template or cfg.postgres.template_db
    if not database_exists(cfg, source):
        raise DatabaseError(
            f"template database '{source}' does not exist - create it first "
            "(e.g. 'docker compose run --rm --no-deps {svc} odoo -d {source} -i base --stop-after-init')"
        )

    strategy = get_strategy(cfg)
    previous = strategy.current_database()

    # Cloning requires ZERO connections on the template: the Odoo service
    # keeps a pool open, so it must be stopped first.
    strategy.stop()
    terminate_connections(cfg, source)

    try:
        clone_database(cfg, source, db)
    except Exception:
        # Never leave a partial clone behind.
        if database_exists(cfg, db):
            try:
                drop_database(cfg, db)
            except Exception:
                pass
        raise

    filestore_result = filestore_copy(cfg, source, db)
    sanitize(cfg, db)

    seeds_ran: list[str] = []
    if not no_seed:
        seeds_ran = run_seeds(cfg, db, branch)

    if use:
        strategy.start(db)
        served = db
    elif previous is not None and database_exists(cfg, previous):
        strategy.start(previous)
        served = previous
    else:
        strategy.start(None)
        served = None  # back to the base config

    return {
        "db": db,
        "source": source,
        "filestore": filestore_result,
        "seeds": seeds_ran,
        "served": served,
    }
