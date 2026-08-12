"""Seed execution and the generic `odoo shell` channel.

Both the sanitizer and the seeds run through the same ephemeral channel:
`docker compose run --rm --no-deps <service> odoo shell -d <db> --no-http`
with the code piped on stdin. An ephemeral container avoids port conflicts
with the running service.

Seeds are loose files (no __init__.py, no package install) that receive
only the Odoo `env` - they never import dbctl. The seeds folder is mounted
via an explicit `-v <abs_path>:<mount>` on the ephemeral container, so
seeding does NOT depend on the compose override (dbctl create seeds before
it writes the override).
"""

from __future__ import annotations

from dbctl.config import Config
from dbctl.docker import compose
from dbctl.errors import DockerError, SeedError
from dbctl.naming import slugify

_RAN_MARKER = "DBCTL_SEED_RAN:"


def run_python(
    cfg: Config,
    db: str,
    code: str,
    *,
    extra_volumes: list[str] | None = None,
    purpose: str = "script",
) -> str:
    """Execute ``code`` inside an ephemeral Odoo shell on ``db``."""
    args: list[str] = ["run", "--rm", "--no-deps"]
    for volume in extra_volumes or []:
        args += ["-v", volume]
    args += [cfg.odoo.compose_service, "odoo", "shell", "-d", db, "--no-http"]
    try:
        return compose(
            cfg.project_root,
            cfg.compose_files,
            args,
            input=code,
            capture=True,
        )
    except DockerError as exc:
        raise SeedError(
            f"odoo shell failed on database '{db}' ({purpose}):\n{exc}"
        ) from exc


def run_seeds(cfg: Config, db: str, branch: str) -> list[str]:
    """Run base.py (always) and branches/<slug>.py (when present).

    Returns the list of seed files that ran. The bootstrap runs both files
    in one shell session and commits once at the end: a failure in either
    file leaves no partial commit.
    """
    if cfg.seeds.path is None or not cfg.seeds.path.is_dir():
        return []
    slug = slugify(branch)
    mount = cfg.seeds.mount
    bootstrap = f'''import importlib.util
from pathlib import Path

def _run_seed(path):
    spec = importlib.util.spec_from_file_location("dbctl_seed", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(env)
    print("{_RAN_MARKER}" + str(path))

mount = Path({mount!r})
base = mount / "base.py"
if base.is_file():
    _run_seed(base)
branch_seed = mount / "branches" / ({slug!r} + ".py")
if branch_seed.is_file():
    _run_seed(branch_seed)
env.cr.commit()
'''
    out = run_python(
        cfg,
        db,
        bootstrap,
        extra_volumes=[f"{cfg.seeds.path}:{mount}"],
        purpose="seeds",
    )
    ran: list[str] = []
    for line in out.splitlines():
        if _RAN_MARKER in line:
            ran.append(line.split(_RAN_MARKER, 1)[1])
    return list(dict.fromkeys(ran))  # dedupe REPL echoes
