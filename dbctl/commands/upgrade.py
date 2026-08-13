"""dbctl upgrade - apply schema changes (-u / -i) to the branch database.

Module resolution precedence (plan: auto-detect-changed-modules):
  -m explicit > --all > detection (when [modules].detect) >
  odoo.default_modules > "nothing to do", exit 0.

Detection compares the branch against the base ref (merge-base, committed
AND uncommitted). Modules detected but not installed in the database go to
`-i` instead of `-u` (when [modules].install_new).
"""

from __future__ import annotations

from dbctl import modules as modules_detect
from dbctl import logging as dlog
from dbctl.commands import dry, target_db
from dbctl.config import Config
from dbctl.errors import ConfigError, DatabaseError
from dbctl.postgres import database_exists, installed_modules
from dbctl.strategies import get_strategy


def run(
    cfg: Config,
    *,
    modules: list[str] | None = None,
    all_modules: bool = False,
    detect: bool | None = None,
) -> dict:
    branch, db = target_db(cfg)
    if not dry() and not database_exists(cfg, db):
        raise DatabaseError(
            f"database '{db}' does not exist - run 'dbctl create' first "
            f"(branch '{branch}')."
        )

    detection = None
    upgrade_modules: list[str] = []
    install_modules: list[str] = []

    if all_modules:
        upgrade_modules = ["all"]
    elif modules:
        upgrade_modules = modules
    else:
        use_detect = cfg.modules.detect if detect is None else detect
        if use_detect:
            detection = modules_detect.detect(cfg)
            dlog.info(
                "detection",
                base_ref=detection["base_ref"],
                base_sha=detection["base_sha"],
                modules=detection["modules"],
                unmatched=detection["unmatched"],
            )
            if detection["modules"]:
                installed = installed_modules(cfg, db)
                if installed is None or not cfg.modules.install_new:
                    upgrade_modules = detection["modules"]
                else:
                    upgrade_modules = [
                        m for m in detection["modules"] if m in installed
                    ]
                    install_modules = [
                        m for m in detection["modules"] if m not in installed
                    ]
                dlog.info(
                    "upgrade_plan",
                    db=db,
                    modules=upgrade_modules,
                    install=install_modules,
                    reason="detected",
                )
            elif detection["changed_paths"]:
                # Files changed, but none maps to a module (e.g. README).
                dlog.info(
                    "upgrade_nothing",
                    db=db,
                    reason="no module changed",
                    changed_paths=detection["changed_paths"],
                )
                return {
                    "db": db,
                    "nothing": True,
                    "reason": "no module changed",
                    "detection": detection,
                }
            else:
                # Literally nothing changed since the base (on the base
                # branch): fall back to the configured default modules.
                if cfg.odoo.default_modules:
                    upgrade_modules = cfg.odoo.default_modules
                    dlog.info(
                        "upgrade_plan",
                        db=db,
                        modules=upgrade_modules,
                        install=[],
                        reason="nothing changed; default_modules fallback",
                    )
                else:
                    dlog.info(
                        "upgrade_nothing",
                        db=db,
                        reason="nothing changed",
                    )
                    return {
                        "db": db,
                        "nothing": True,
                        "reason": "nothing changed",
                        "detection": detection,
                    }
        else:
            upgrade_modules = cfg.odoo.default_modules
            if not upgrade_modules:
                raise ConfigError(
                    "no modules to upgrade: pass '-m mod1,mod2', use '--all', "
                    "or set odoo.default_modules in .dbctl.toml"
                )

    if upgrade_modules or install_modules:
        get_strategy(cfg).upgrade(db, upgrade_modules, install_modules)
    return {
        "db": db,
        "modules": upgrade_modules,
        "install": install_modules,
        "detection": detection,
    }
