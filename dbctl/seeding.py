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

from pathlib import Path

from dbctl import logging as dlog
from dbctl.config import Config
from dbctl.docker import compose
from dbctl.errors import DockerError, SeedError
from dbctl.naming import slugify

_RAN_MARKER = "DBCTL_SEED_RAN:"
_AUTO_OK = "DBCTL_AUTOSEED:"
_AUTO_SKIP = "DBCTL_AUTOSEED_SKIP:"
_AUTOSEED_SRC = Path(__file__).with_name("autoseed_shell.py")


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
        raise SeedError(f"odoo shell failed on database '{db}' ({purpose}):\n{exc}") from exc


def _auto_code(cfg: Config) -> str:
    """Generator source + the call for the repo's modules ([seeds].auto)."""
    from dbctl.modules import repo_modules

    call = (
        f"run_auto(env, {repo_modules(cfg)!r}, {cfg.seeds.auto_count!r}, "
        f"{cfg.seeds.auto_exclude!r})\n"
    )
    return _AUTOSEED_SRC.read_text(encoding="utf-8") + "\n" + call


def run_seeds(cfg: Config, db: str, branch: str) -> list[str]:
    """Auto-seed (when [seeds].auto), then base.py and branches/<slug>.py.

    Returns what ran: ``auto:<model>(<n>)`` entries plus the seed files.
    Everything runs in one shell session and commits once at the end: a
    failing seed file leaves no partial commit (auto-seed isolates each
    model in a savepoint, so a rejected model is skipped, not fatal).
    """
    has_dir = cfg.seeds.path is not None and cfg.seeds.path.is_dir()
    if not has_dir and not cfg.seeds.auto:
        return []
    slug = slugify(branch)
    mount = cfg.seeds.mount
    auto = _auto_code(cfg) if cfg.seeds.auto else ""
    files = (
        f'''import importlib.util
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
'''
        if has_dir
        else ""
    )
    bootstrap = auto + files + "env.cr.commit()\n"
    out = run_python(
        cfg,
        db,
        bootstrap,
        extra_volumes=[f"{cfg.seeds.path}:{mount}"] if has_dir else None,
        purpose="seeds",
    )
    ran: list[str] = []
    for line in out.splitlines():
        if line.startswith(_AUTO_SKIP):
            model, _, reason = line[len(_AUTO_SKIP) :].partition(":")
            dlog.warning("autoseed_skip", model=model, reason=reason)
        elif line.startswith(_AUTO_OK):
            model, _, count = line[len(_AUTO_OK) :].partition(":")
            ran.append(f"auto:{model}({count})")
        elif _RAN_MARKER in line:
            ran.append(line.split(_RAN_MARKER, 1)[1])
    return list(dict.fromkeys(ran))  # dedupe REPL echoes
