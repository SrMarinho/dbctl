"""Filestore operations.

Executed INSIDE an ephemeral service container (`docker compose run
--rm --no-deps`) - never on the host. The data_dir belongs to the odoo
user (uid 101); copying via the container keeps ownership correct and
avoids sudo/chown on the host. The project's entrypoint must pass
non-odoo commands through (`exec "$@"`), which is a documented project
requirement.
"""

from __future__ import annotations

from dbctl.config import Config
from dbctl.docker import compose
from dbctl.errors import DatabaseError

_MISSING = "DBCTL_FILESTORE_MISSING"
_COPIED = "DBCTL_FILESTORE_COPIED"


def _run_in_service(cfg: Config, args: list[str], *, capture: bool = True) -> str:
    return compose(
        cfg.project_root,
        cfg.compose_files,
        ["run", "--rm", "--no-deps", cfg.odoo.compose_service] + args,
        capture=capture,
    )


def _filestore_dir(cfg: Config, db: str) -> str:
    return f"{cfg.odoo.data_dir}/filestore/{db}"


def copy(cfg: Config, source_db: str, target_db: str) -> str:
    """Copy the filestore of ``source_db`` to ``target_db``.

    A missing source is valid (a database without attachments): logs a
    marker and returns "missing".
    """
    src = _filestore_dir(cfg, source_db)
    dst = _filestore_dir(cfg, target_db)
    script = (
        f'if [ -d "{src}" ]; then cp -a "{src}" "{dst}" && echo {_COPIED}; else echo {_MISSING}; fi'
    )
    out = _run_in_service(cfg, ["sh", "-c", script], capture=True)
    if _MISSING in out:
        return "missing"
    return "copied"


def remove(cfg: Config, db: str) -> None:
    """Remove the filestore directory of ``db``. Prefix-guarded like drops."""
    if not db.startswith(cfg.postgres.db_prefix):
        raise DatabaseError(
            f"refusing to remove filestore of '{db}': it does not start with "
            f"db_prefix '{cfg.postgres.db_prefix}'."
        )
    _run_in_service(cfg, ["sh", "-c", f'rm -rf "{_filestore_dir(cfg, db)}"'], capture=True)
