"""Typer CLI - argument parsing, output formatting, exit codes only.

No business rule lives here: commands/ orchestrates each use case and
returns plain data for this module to format.
"""

from __future__ import annotations

import os
import re
import traceback
from pathlib import Path

import typer

from dbctl import __version__
from dbctl.commands import (
    create as create_cmd,
    drop as drop_cmd,
    list_dbs as list_cmd,
    reset as reset_cmd,
    seed as seed_cmd,
    status as status_cmd,
    unuse as unuse_cmd,
    upgrade as upgrade_cmd,
    use as use_cmd,
)
from dbctl.config import Config, load_config
from dbctl.docker import compose
from dbctl.errors import DbctlError, DockerError
from dbctl.project import find_config

app = typer.Typer(
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    help="One Odoo database per git branch - agnostic, Docker-based.",
)


@app.callback()
def _main(
    ctx: typer.Context,
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show full tracebacks on errors."
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        "-p",
        help="Project root (default: discover the git repo from the cwd).",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        help="Path to the .dbctl.toml (default: discovery, spec 5.0).",
    ),
    version: bool = typer.Option(
        False, "--version", help="Show the dbctl version and exit."
    ),
) -> None:
    if version:
        typer.echo(f"dbctl {__version__}")
        raise typer.Exit()
    ctx.obj = {"verbose": verbose, "project": project, "config": config}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _load_config(ctx: typer.Context, *, quiet: bool = False) -> Config:
    """Resolve project root + config file (spec 5.0) and load the config."""
    opts = ctx.obj
    explicit = opts.get("config") or os.environ.get("DBCTL_CONFIG")
    root_override = (
        Path(opts["project"]).expanduser().resolve()
        if opts.get("project")
        else None
    )
    start = root_override if root_override else Path.cwd()
    config_path, project_root = find_config(
        start,
        explicit=Path(explicit).expanduser().resolve() if explicit else None,
        root_override=root_override,
    )
    cfg = load_config(project_root, config_path)
    if not quiet:
        for warning in cfg.warnings:
            typer.echo(f"warning: {warning}", err=True)
    return cfg


def _run(ctx: typer.Context, fn) -> None:
    verbose: bool = ctx.obj["verbose"]
    try:
        fn()
    except DbctlError as exc:
        if verbose:
            traceback.print_exc()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:  # unexpected - still no raw traceback unless -v
        if verbose:
            traceback.print_exc()
        typer.echo(f"Error: unexpected {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc


def _ask(message: str) -> bool:
    return typer.confirm(message, default=False)


def _web_url(cfg: Config) -> str | None:
    try:
        out = compose(
            cfg.project_root,
            cfg.compose_files,
            ["port", cfg.odoo.compose_service, "8069"],
            capture=True,
        )
    except DockerError:
        return None
    match = re.match(r"^.*:(\d+)$", out.strip())
    return f"http://localhost:{match.group(1)}" if match else None


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

@app.command()
def status(ctx: typer.Context) -> None:
    """Show project, branch, target database and what is being served."""
    def _do() -> None:
        cfg = _load_config(ctx)
        info = status_cmd.run(cfg)
        served = info["served"] or "none (base config)"
        seed = info["branch_seed"] or "none"
        typer.echo(f"project:     {info['project']}")
        typer.echo(f"config:      {info['config']}")
        typer.echo(f"branch:      {info['branch']}")
        typer.echo(f"target db:   {info['target_db']}")
        typer.echo(f"exists:      {'yes' if info['exists'] else 'no'}")
        typer.echo(f"served now:  {served}")
        typer.echo(f"template:    {info['template']}")
        typer.echo(f"branch seed: {seed}")
        if info["dirty"]:
            typer.echo(
                "warning: working tree has uncommitted changes - the branch "
                "database may not have the schema your code expects yet.",
                err=True,
            )

    _run(ctx, _do)


@app.command()
def create(
    ctx: typer.Context,
    from_template: str | None = typer.Option(
        None, "--from", help="Template database (default: postgres.template_db)."
    ),
    no_seed: bool = typer.Option(
        False, "--no-seed", help="Skip seeds after cloning."
    ),
    use: bool = typer.Option(
        False, "--use", help="Serve the new database right away."
    ),
) -> None:
    """Clone the template into the branch database (filestore + sanitize + seeds)."""
    def _do() -> None:
        cfg = _load_config(ctx)
        result = create_cmd.run(
            cfg, template=from_template, no_seed=no_seed, use=use
        )
        typer.echo(f"created {result['db']} from {result['source']}")
        typer.echo(f"filestore: {result['filestore']}")
        if result["seeds"]:
            typer.echo("seeds: " + ", ".join(result["seeds"]))
        if result["served"]:
            url = _web_url(cfg)
            typer.echo(f"now serving {result['served']}" + (f" ({url})" if url else ""))
        elif result["served"] is None and not use:
            typer.echo("restored the service to the base config")

    _run(ctx, _do)


@app.command()
def use(ctx: typer.Context) -> None:
    """Point the Odoo service at the branch database."""
    def _do() -> None:
        cfg = _load_config(ctx)
        result = use_cmd.run(cfg)
        url = _web_url(cfg)
        typer.echo(f"serving {result['db']}" + (f" ({url})" if url else ""))

    _run(ctx, _do)


@app.command()
def unuse(ctx: typer.Context) -> None:
    """Remove the compose override; next `docker compose up` uses base config."""
    def _do() -> None:
        cfg = _load_config(ctx)
        result = unuse_cmd.run(cfg)
        if result["removed"]:
            typer.echo(
                f"removed {result['override']} - the project is back to its "
                "original behavior (the running service keeps serving until "
                "recreated without the override)."
            )
        else:
            typer.echo("no override file to remove.")

    _run(ctx, _do)


@app.command()
def upgrade(
    ctx: typer.Context,
    modules: str | None = typer.Option(
        None, "--modules", "-m", help="Comma-separated modules to upgrade."
    ),
    all_modules: bool = typer.Option(
        False, "--all", help="Upgrade all modules (-u all)."
    ),
) -> None:
    """Apply schema upgrades (-u) to the branch database only."""
    def _do() -> None:
        cfg = _load_config(ctx)
        module_list = (
            [part.strip() for part in modules.split(",") if part.strip()]
            if modules
            else None
        )
        result = upgrade_cmd.run(
            cfg, modules=module_list, all_modules=all_modules
        )
        typer.echo(f"upgraded {result['db']} with modules: {','.join(result['modules'])}")

    _run(ctx, _do)


@app.command()
def seed(ctx: typer.Context) -> None:
    """Run base.py and the branch seed, if present."""
    def _do() -> None:
        cfg = _load_config(ctx)
        result = seed_cmd.run(cfg)
        if result.get("skipped"):
            typer.echo(
                "seeds not configured or seeds dir missing - nothing to do."
            )
        elif result["ran"]:
            typer.echo("ran seeds: " + ", ".join(result["ran"]))
        else:
            typer.echo("no seed files found to run.")

    _run(ctx, _do)


@app.command("list")
def list_dbs(ctx: typer.Context) -> None:
    """List the project's branch databases (prefix only) with sizes."""
    def _do() -> None:
        cfg = _load_config(ctx)
        result = list_cmd.run(cfg)
        if not result["rows"]:
            typer.echo(f"no databases with prefix '{cfg.postgres.db_prefix}'.")
            return
        width = max(len(name) for name, _ in result["rows"])
        typer.echo(f"{'DATABASE'.ljust(width)}  SIZE      BRANCH  SERVED")
        for name, size in result["rows"]:
            is_current = "yes" if name == result["current"] else ""
            is_served = "yes" if name == result["served"] else ""
            typer.echo(f"{name.ljust(width)}  {size.ljust(8)}  {is_current.ljust(6)}  {is_served}")

    _run(ctx, _do)


@app.command()
def drop(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
    db: str | None = typer.Option(
        None, "--db", help="Database to drop (default: current branch's)."
    ),
) -> None:
    """Drop a branch database and its filestore (prefix-guarded)."""
    def _do() -> None:
        cfg = _load_config(ctx)
        result = drop_cmd.run(cfg, yes=yes, db=db, ask=_ask)
        if result["existed"]:
            typer.echo(f"dropped {result['db']} (database + filestore)")
        else:
            typer.echo(f"{result['db']} did not exist; nothing to drop.")

    _run(ctx, _do)


@app.command()
def reset(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Drop and recreate the branch database from the template (with seeds)."""
    def _do() -> None:
        cfg = _load_config(ctx)
        result = reset_cmd.run(cfg, yes=yes, ask=_ask)
        typer.echo(f"reset {result['db']} from {result['source']}")
        if result["seeds"]:
            typer.echo("seeds: " + ", ".join(result["seeds"]))
        url = _web_url(cfg)
        typer.echo("now serving " + result["db"] + (f" ({url})" if url else ""))

    _run(ctx, _do)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
