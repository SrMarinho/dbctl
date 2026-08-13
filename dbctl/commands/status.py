"""dbctl status - read-only project/database report. Always side-effect free."""

from __future__ import annotations

from dbctl.commands import hook_info, target_db
from dbctl.config import Config
from dbctl.errors import ConfigError, DockerError, GitError
from dbctl.naming import slugify
from dbctl.postgres import database_exists
from dbctl.project import working_tree_dirty
from dbctl.strategies import get_strategy


def _changed_preview(cfg: Config) -> dict:
    """Detection preview for status. Side-effect-free (git read-only).

    Never raises: any failure becomes {"error": ...} so `status` keeps its
    no-fail guarantee.
    """
    if not cfg.modules.detect:
        return {"enabled": False, "modules": [], "base_ref": None, "base_sha": None}
    try:
        from dbctl.modules import detect

        result = detect(cfg)
        return {
            "enabled": True,
            "modules": result["modules"],
            "base_ref": result["base_ref"],
            "base_sha": result["base_sha"],
            "error": None,
        }
    except (ConfigError, GitError, DockerError) as exc:
        return {
            "enabled": True,
            "modules": [],
            "base_ref": None,
            "base_sha": None,
            "error": str(exc),
        }


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
        "hook": hook_info(cfg),
        "changed_modules": _changed_preview(cfg),
        "dirty": working_tree_dirty(cfg.project_root),
    }
