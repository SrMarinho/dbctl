"""dbctl create - branch database: clone from a template OR fresh.

With a template (config ``postgres.template_db`` or ``--from``) the branch
database is a clone: filestore copied, sanitized, seeds, then the branch
schema. Without any template the database is created EMPTY and initialized
in place: ``odoo -d <db> -i base[,default_modules][,changed modules]``, then
seeds. Cloning is always opt-in.
"""

from __future__ import annotations

from dbctl import logging as dlog
from dbctl.commands import dry, target_db
from dbctl.config import Config
from dbctl.errors import DatabaseError
from dbctl.filestore import copy as filestore_copy
from dbctl.postgres import (
    clone_database,
    create_database,
    database_exists,
    drop_database,
    terminate_connections,
)
from dbctl.sanitize import sanitize
from dbctl.seeding import run_seeds
from dbctl.strategies import get_strategy


def _dedupe(items: list[str]) -> list[str]:
    """Dedupe preserving order (base + default_modules + detected)."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def run(
    cfg: Config,
    *,
    template: str | None = None,
    no_seed: bool = False,
    use: bool = False,
    no_upgrade: bool = False,
) -> dict:
    branch, db = target_db(cfg)
    if not dry() and database_exists(cfg, db):
        raise DatabaseError(f"database '{db}' already exists - use 'dbctl reset' to recreate it.")
    source = template or cfg.postgres.template_db
    fresh = source is None
    if not dry() and source is not None and not database_exists(cfg, source):
        raise DatabaseError(
            f"template database '{source}' does not exist - create it first "
            "(e.g. 'docker compose run --rm --no-deps {svc} odoo -d "
            f"{source} -i base --stop-after-init'), or remove template_db "
            "from the config to create a fresh database"
        )
    dlog.info(
        "create_start",
        db=db,
        source=source,
        fresh=fresh,
        branch=branch,
        no_seed=no_seed,
        no_upgrade=no_upgrade,
    )

    strategy = get_strategy(cfg)
    previous = strategy.current_database()

    # Cloning requires ZERO connections on the template: the Odoo service
    # keeps a pool open, so it must be stopped first. The fresh path also
    # stops it so the schema init does not fight the running container
    # over the filestore.
    dlog.info("create_phase", phase="stop", db=db)
    strategy.stop()

    try:
        if fresh:
            dlog.info("create_phase", phase="create", db=db)
            create_database(cfg, db)
        else:
            assert source is not None  # fresh == (source is None)
            dlog.info("create_phase", phase="terminate_connections", source=source)
            terminate_connections(cfg, source)
            dlog.info("create_phase", phase="clone", source=source, target=db)
            clone_database(cfg, source, db)
    except Exception:
        # Never leave a partial database behind.
        if database_exists(cfg, db):
            try:
                dlog.warning("create_phase", phase="cleanup_partial_clone", db=db)
                drop_database(cfg, db)
            except Exception:
                pass
        raise

    filestore_result = "none"
    if not fresh:
        assert source is not None  # fresh == (source is None)
        dlog.info("create_phase", phase="filestore", source=source, target=db)
        filestore_result = filestore_copy(cfg, source, db)
        dlog.info("create_phase", phase="sanitize", db=db)
        sanitize(cfg, db)

    # Schema: the database should be born with THIS branch's schema. On a
    # fresh database there is nothing to upgrade, only to install (base +
    # configured defaults + modules changed on this branch).
    upgrade_info: dict | None = None
    if not no_upgrade:
        try:
            from dbctl import modules as modules_detect

            exclude = set(cfg.modules.exclude)
            detection = None
            to_upgrade: list[str] = []
            to_install: list[str] = []
            excluded: list[str] = []
            if fresh:
                defaults = [m for m in cfg.odoo.default_modules if m not in exclude]
                excluded = [m for m in cfg.odoo.default_modules if m in exclude]
                to_install = _dedupe(["base"] + defaults)
                if cfg.modules.detect:
                    detection = modules_detect.detect(cfg)
                    to_install = _dedupe(to_install + detection["modules"])
                    excluded = _dedupe(excluded + detection["excluded"])
            elif cfg.modules.detect:
                from dbctl.postgres import installed_modules

                detection = modules_detect.detect(cfg)
                excluded = detection["excluded"]
                if detection["modules"]:
                    installed = installed_modules(cfg, db)
                    if installed is None or not cfg.modules.install_new:
                        to_upgrade = detection["modules"]
                    else:
                        to_upgrade = [m for m in detection["modules"] if m in installed]
                        to_install = [m for m in detection["modules"] if m not in installed]
            if to_upgrade or to_install:
                dlog.info(
                    "create_phase",
                    phase="upgrade",
                    db=db,
                    modules=to_upgrade,
                    install=to_install,
                    excluded=excluded,
                    base_ref=detection["base_ref"] if detection else None,
                    base_sha=detection["base_sha"] if detection else None,
                )
                strategy.apply_schema(db, to_upgrade, to_install)
                upgrade_info = {
                    "modules": to_upgrade,
                    "install": to_install,
                    "excluded": excluded,
                    "base_ref": detection["base_ref"] if detection else None,
                    "base_sha": detection["base_sha"] if detection else None,
                }
        except Exception as exc:  # detection/schema must not break `create`
            dlog.warning(
                "create_phase",
                phase="detection_skipped",
                db=db,
                error=str(exc),
            )
            upgrade_info = {"error": str(exc)}
    elif fresh:
        dlog.warning(
            "create_phase",
            phase="no_upgrade_fresh",
            db=db,
            message="--no-upgrade on a fresh database: it stays empty (no schema)",
        )

    seeds_ran: list[str] = []
    if not no_seed:
        # Seeds need Odoo tables: on the fresh path they run after the
        # schema init; on the clone path the schema is already there.
        seeds_ran = run_seeds(cfg, db, branch)
    dlog.info("create_phase", phase="seeds", db=db, files=seeds_ran)

    if use:
        strategy.start(db)
        served = db
    elif previous is not None and database_exists(cfg, previous):
        strategy.start(previous)
        served = previous
    else:
        strategy.start(None)
        served = None  # back to the base config

    dlog.info("create_phase", phase="start", db=served if served else "base")

    return {
        "db": db,
        "source": source,
        "filestore": filestore_result,
        "seeds": seeds_ran,
        "upgrade": upgrade_info,
        "served": served,
    }
