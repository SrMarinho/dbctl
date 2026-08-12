"""dbctl status - read-only project/database report. Always side-effect free."""

from __future__ import annotations

from dbctl.commands import target_db
from dbctl.config import Config
from dbctl.naming import slugify
from dbctl.postgres import database_exists
from dbctl.project import working_tree_dirty
from dbctl.strategies import get_strategy


def run(cfg: Config) -> dict:
    branch, db = target_db(cfg)
    strategy = get_strategy(cfg)
    branch_seed = None
    if cfg.seeds.path is not None and cfg.seeds.path.is_dir():
        candidate = cfg.seeds.path / "branches" / f"{slugify(branch)}.py"
        if candidate.is_file():
            branch_seed = candidate
    return {
        "project": str(cfg.project_root),
        "config": str(cfg.path),
        "branch": branch,
        "target_db": db,
        "exists": database_exists(cfg, db),
        "served": strategy.current_database(),
        "template": cfg.postgres.template_db,
        "branch_seed": str(branch_seed) if branch_seed else None,
        "dirty": working_tree_dirty(cfg.project_root),
    }
