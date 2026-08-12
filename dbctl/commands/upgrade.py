"""dbctl upgrade - apply module upgrades (-u) to the branch database only."""

from __future__ import annotations

from dbctl.commands import dry, target_db
from dbctl.config import Config
from dbctl.errors import ConfigError, DatabaseError
from dbctl.postgres import database_exists
from dbctl.strategies import get_strategy


def run(
    cfg: Config,
    *,
    modules: list[str] | None = None,
    all_modules: bool = False,
) -> dict:
    branch, db = target_db(cfg)
    if not dry() and not database_exists(cfg, db):
        raise DatabaseError(
            f"database '{db}' does not exist - run 'dbctl create' first "
            f"(branch '{branch}')."
        )
    if all_modules:
        modules = ["all"]
    elif not modules:
        modules = cfg.odoo.default_modules
        if not modules:
            raise ConfigError(
                "no modules to upgrade: pass '-m mod1,mod2', use '--all', "
                "or set odoo.default_modules in .dbctl.toml"
            )
    get_strategy(cfg).upgrade(db, modules)
    return {"db": db, "modules": modules}
