"""Load and validate the project's .dbctl.toml.

Validation fails BEFORE any side effect, with a message pointing at the
offending key and the file path. All keys accept an environment override
in the DBCTL_<SECTION>_<KEY> pattern (uppercase). Precedence:
env var > file > default.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dbctl.errors import ConfigError

_DB_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_PREFIX_LEN = 56  # keeps prefix + "_" + 6-hex digest <= 63 (Postgres limit)
_STRATEGY_KINDS = ("compose-override", "custom")


@dataclass
class PostgresConfig:
    container: str
    user: str
    password: str
    template_db: str
    db_prefix: str = "dev_"


@dataclass
class OdooConfig:
    container: str
    compose_service: str
    compose_file: str = "docker-compose.yml"
    data_dir: str = "/var/lib/odoo"
    default_modules: list[str] = field(default_factory=list)


@dataclass
class SeedsConfig:
    path: Path | None = None  # absolute; None when not configured
    mount: str = "/mnt/dbctl-seeds"
    configured: bool = False  # True when [seeds] or env override exists


@dataclass
class StrategyCommands:
    start: str | None = None
    stop: str | None = None
    upgrade: str | None = None
    shell: str | None = None


@dataclass
class StrategyConfig:
    kind: str = "compose-override"
    override_file: str = "docker-compose.override.yaml"
    commands: StrategyCommands = field(default_factory=StrategyCommands)


@dataclass
class HooksConfig:
    enabled: bool = True
    stash_dirty: bool = True  # post-checkout stashes uncommitted changes (no data loss)


@dataclass
class ModulesConfig:
    detect: bool = True  # auto-detect changed modules for `upgrade`
    base_ref: str | None = None  # e.g. "origin/main"; None = auto-detect
    manifest: str = "__manifest__.py"  # file marking a module root
    install_new: bool = True  # detected-but-not-installed modules -> -i
    ignore: list[str] = field(default_factory=list)  # globs that never trigger


@dataclass
class Config:
    project_root: Path  # git top-level: base of all relative paths
    path: Path  # the .dbctl.toml file itself (anywhere in the repo tree)
    postgres: PostgresConfig
    odoo: OdooConfig
    seeds: SeedsConfig
    strategy: StrategyConfig
    hooks: HooksConfig = field(default_factory=HooksConfig)
    modules: ModulesConfig = field(default_factory=ModulesConfig)
    warnings: list[str] = field(default_factory=list)

    @property
    def compose_files(self) -> list[str]:
        """Base compose file, plus the override when it exists."""
        files = [self.odoo.compose_file]
        override = self.project_root / self.strategy.override_file
        if override.is_file():
            files.append(self.strategy.override_file)
        return files


def _env(section: str, key: str) -> str | None:
    return os.environ.get(f"DBCTL_{section.upper()}_{key.upper()}")


def _split_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


_TRUE_LITERALS = {"1", "true", "yes", "on"}
_FALSE_LITERALS = {"0", "false", "no", "off"}


def _parse_bool(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_LITERALS:
        return True
    if normalized in _FALSE_LITERALS:
        return False
    raise ConfigError(
        f"invalid value for {key}: '{value}' - expected one of "
        "1/true/yes/on or 0/false/no/off (case-insensitive)"
    )


def _require(section: str, raw: dict, key: str, missing: list[str]) -> str:
    """File value, env override, or a missing-key entry."""
    env_value = _env(section, key)
    if env_value is not None:
        return env_value
    value = raw.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        missing.append(f"[{section}].{key}")
        return ""
    return str(value)


def load_config(project_root: Path, config_path: Path) -> Config:
    """Read, validate and normalize the configuration.

    ``project_root`` is the git top-level of the repository (the base of
    every relative path in the config - spec 5.0); ``config_path`` is the
    .dbctl.toml file itself, anywhere inside the repository.
    """
    cfg_path = config_path.expanduser().resolve()
    root = project_root.expanduser().resolve()
    if not cfg_path.is_file():
        raise ConfigError(f"missing configuration file: {cfg_path}")
    try:
        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {cfg_path}: {exc}") from exc

    warnings: list[str] = []

    # --- [postgres] ------------------------------------------------------
    pg_raw = data.get("postgres", {})
    missing: list[str] = []
    container = _require("postgres", pg_raw, "container", missing)
    user = _require("postgres", pg_raw, "user", missing)
    template_db = _require("postgres", pg_raw, "template_db", missing)
    password = _env("postgres", "password") or (
        pg_raw.get("password") if isinstance(pg_raw.get("password"), str) else None
    )
    if password is None:
        missing.append("[postgres].password (or set DBCTL_POSTGRES_PASSWORD)")
    db_prefix = _env("postgres", "db_prefix") or str(pg_raw.get("db_prefix", "dev_"))

    if not _DB_PREFIX_RE.match(db_prefix):
        missing.append(
            f"[postgres].db_prefix '{db_prefix}' must match ^[a-z][a-z0-9_]*$ "
            "(it is the protection against dropping someone else's database)"
        )
    elif len(db_prefix) > _MAX_PREFIX_LEN:
        missing.append(
            f"[postgres].db_prefix must be at most {_MAX_PREFIX_LEN} chars "
            "so branch database names stay <= 63 chars"
        )

    if missing:
        raise ConfigError(
            f"invalid or incomplete configuration in {cfg_path}:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
    assert password is not None  # guaranteed by the check above

    # --- [odoo] ----------------------------------------------------------
    od_raw = data.get("odoo", {})
    missing = []
    odoo_container = _require("odoo", od_raw, "container", missing)
    compose_service = _require("odoo", od_raw, "compose_service", missing)
    if missing:
        raise ConfigError(
            f"invalid or incomplete configuration in {cfg_path}:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
    compose_file = _env("odoo", "compose_file") or str(
        od_raw.get("compose_file", "docker-compose.yml")
    )
    data_dir = _env("odoo", "data_dir") or str(od_raw.get("data_dir", "/var/lib/odoo"))
    default_modules = _split_list(_env("odoo", "default_modules"))
    if default_modules is None:
        raw_modules = od_raw.get("default_modules", [])
        default_modules = list(raw_modules) if isinstance(raw_modules, list) else []

    # --- [seeds] ---------------------------------------------------------
    sd_raw = data.get("seeds", {})
    seeds_configured = bool(sd_raw) or any(
        os.environ.get(k) for k in ("DBCTL_SEEDS_PATH", "DBCTL_SEEDS_MOUNT")
    )
    seeds_path_raw = _env("seeds", "path")
    if seeds_path_raw is None and sd_raw.get("path") is not None:
        seeds_path_raw = str(sd_raw["path"])
    seeds_path: Path | None = None
    if seeds_path_raw:
        # Resolved from the git repo root (spec 5.0/rule 7), never from the
        # folder where the .dbctl.toml happens to live.
        seeds_path = (root / seeds_path_raw).resolve()
        if not seeds_path.is_dir():
            warnings.append(
                f"seeds.path '{seeds_path}' does not exist - 'dbctl seed' will be a no-op"
            )
    mount = _env("seeds", "mount") or str(sd_raw.get("mount", "/mnt/dbctl-seeds"))

    # --- [strategy] ------------------------------------------------------
    st_raw = data.get("strategy", {})
    kind = _env("strategy", "kind") or str(st_raw.get("kind", "compose-override"))
    if kind not in _STRATEGY_KINDS:
        raise ConfigError(
            f"invalid [strategy].kind '{kind}' in {cfg_path}: "
            f"valid values are {', '.join(_STRATEGY_KINDS)}"
        )
    override_file = _env("strategy", "override_file") or str(
        st_raw.get("override_file", "docker-compose.override.yaml")
    )
    cmds_raw = st_raw.get("commands", {}) if isinstance(st_raw.get("commands", {}), dict) else {}

    def _cmd(key: str) -> str | None:
        env_value = _env("strategy_commands", key)
        if env_value is not None:
            return env_value
        value = cmds_raw.get(key)
        return str(value) if isinstance(value, str) and value.strip() else None

    commands = StrategyCommands(
        start=_cmd("start"),
        stop=_cmd("stop"),
        upgrade=_cmd("upgrade"),
        shell=_cmd("shell"),
    )
    if kind == "custom" and (not commands.start or not commands.stop):
        raise ConfigError(
            f"strategy.kind = 'custom' in {cfg_path} requires "
            "[strategy.commands].start and [strategy.commands].stop"
        )

    # --- [hooks] ---------------------------------------------------------
    def _hook_bool(key: str, default: bool) -> bool:
        env_value = _env("hooks", key)
        if env_value is not None:
            return _parse_bool(env_value, f"DBCTL_HOOKS_{key.upper()}")
        raw = data.get("hooks", {}).get(key, default)
        if not isinstance(raw, bool):
            raise ConfigError(
                f"invalid [hooks].{key} in {cfg_path}: expected a TOML "
                f"boolean (true/false), got {raw!r}. "
                "A missing [hooks] block is equivalent to the defaults."
            )
        return raw

    enabled = _hook_bool("enabled", True)
    stash_dirty = _hook_bool("stash_dirty", True)

    # --- [modules] -------------------------------------------------------
    md_raw = data.get("modules", {})

    def _bool_key(key: str, env_name: str, default: bool) -> bool:
        env_value = _env("modules", key)
        if env_value is not None:
            return _parse_bool(env_value, env_name)
        raw = md_raw.get(key, default)
        if not isinstance(raw, bool):
            raise ConfigError(
                f"invalid [modules].{key} in {cfg_path}: expected a TOML "
                f"boolean (true/false), got {raw!r}"
            )
        return raw

    detect_enabled = _bool_key("detect", "DBCTL_MODULES_DETECT", True)
    install_new = _bool_key("install_new", "DBCTL_MODULES_INSTALL_NEW", True)

    base_ref_value = _env("modules", "base_ref")
    if base_ref_value is None and isinstance(md_raw.get("base_ref"), str):
        base_ref_value = md_raw["base_ref"].strip() or None
    manifest_value = _env("modules", "manifest") or str(md_raw.get("manifest", "__manifest__.py"))
    env_ignore = _env("modules", "ignore")
    if env_ignore is not None:
        ignore = [part.strip() for part in env_ignore.split(",") if part.strip()]
    else:
        raw_ignore = md_raw.get("ignore", [])
        ignore = list(raw_ignore) if isinstance(raw_ignore, list) else []

    return Config(
        project_root=root,
        path=cfg_path,
        postgres=PostgresConfig(
            container=container,
            user=user,
            password=password,
            template_db=template_db,
            db_prefix=db_prefix,
        ),
        odoo=OdooConfig(
            container=odoo_container,
            compose_service=compose_service,
            compose_file=compose_file,
            data_dir=data_dir,
            default_modules=default_modules,
        ),
        seeds=SeedsConfig(path=seeds_path, mount=mount, configured=seeds_configured),
        strategy=StrategyConfig(
            kind=kind,
            override_file=override_file,
            commands=commands,
        ),
        hooks=HooksConfig(enabled=enabled, stash_dirty=stash_dirty),
        modules=ModulesConfig(
            detect=detect_enabled,
            base_ref=base_ref_value,
            manifest=manifest_value,
            install_new=install_new,
            ignore=ignore,
        ),
        warnings=warnings,
    )
