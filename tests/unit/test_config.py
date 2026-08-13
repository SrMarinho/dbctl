"""Unit tests for dbctl.config (spec V3: invalid config -> ConfigError, exit 3)."""

from __future__ import annotations

import pytest

from dbctl.config import load_config
from dbctl.errors import ConfigError


def test_load_valid_config(tmp_config) -> None:
    cfg = load_config(tmp_config, tmp_config / ".dbctl.toml")
    assert cfg.postgres.container == "pg-test"
    assert cfg.postgres.db_prefix == "dev_"
    assert cfg.odoo.compose_service == "web"
    assert cfg.strategy.kind == "compose-override"
    assert cfg.hooks.enabled is True
    assert cfg.modules.detect is True
    assert cfg.compose_files == ["docker-compose.yml"]


def test_missing_file(tmp_config) -> None:
    with pytest.raises(ConfigError, match="missing configuration file"):
        load_config(tmp_config, tmp_config / "nope.toml")


def test_invalid_toml(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text("[postgres\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(tmp_config, tmp_config / ".dbctl.toml")


def test_missing_required_keys(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text('[postgres]\ncontainer = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_config, tmp_config / ".dbctl.toml")
    assert "[postgres].user" in str(exc.value)
    assert "[postgres].template_db" in str(exc.value)
    assert "[postgres].password" in str(exc.value)


def test_missing_odoo_keys(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"\[odoo\].container"):
        load_config(tmp_config, tmp_config / ".dbctl.toml")


def test_invalid_db_prefix(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\ndb_prefix="Dev-9!"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="db_prefix"):
        load_config(tmp_config, tmp_config / ".dbctl.toml")


def test_db_prefix_too_long(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        f'db_prefix="{"dev_" * 20}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="63"):
        load_config(tmp_config, tmp_config / ".dbctl.toml")


def test_env_override_beats_file(tmp_config, monkeypatch) -> None:
    monkeypatch.setenv("DBCTL_POSTGRES_CONTAINER", "env-container")
    monkeypatch.setenv("DBCTL_POSTGRES_PASSWORD", "env-pass")
    monkeypatch.setenv("DBCTL_STRATEGY_KIND", "custom")
    monkeypatch.setenv("DBCTL_STRATEGY_COMMANDS_START", "true")
    monkeypatch.setenv("DBCTL_STRATEGY_COMMANDS_STOP", "false")
    cfg = load_config(tmp_config, tmp_config / ".dbctl.toml")
    assert cfg.postgres.container == "env-container"
    assert cfg.postgres.password == "env-pass"
    assert cfg.strategy.kind == "custom"


def test_invalid_strategy_kind(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        + '[strategy]\nkind = "teleport"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="kind"):
        load_config(tmp_config, tmp_config / ".dbctl.toml")


def test_custom_strategy_requires_commands(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n' + '[strategy]\nkind = "custom"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="start and .*stop"):
        load_config(tmp_config, tmp_config / ".dbctl.toml")


def test_hooks_enabled_must_be_bool(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n' + '[hooks]\nenabled = "yes"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"\[hooks\].enabled"):
        load_config(tmp_config, tmp_config / ".dbctl.toml")


def test_hooks_disabled_via_env(tmp_config, monkeypatch) -> None:
    monkeypatch.setenv("DBCTL_HOOKS_ENABLED", "0")
    cfg = load_config(tmp_config, tmp_config / ".dbctl.toml")
    assert cfg.hooks.enabled is False


def test_modules_boolean_validation(tmp_config) -> None:
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n' + '[modules]\ndetect = "false"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"\[modules\].detect"):
        load_config(tmp_config, tmp_config / ".dbctl.toml")


def test_modules_env_overrides(tmp_config, monkeypatch) -> None:
    monkeypatch.setenv("DBCTL_MODULES_DETECT", "false")
    monkeypatch.setenv("DBCTL_MODULES_INSTALL_NEW", "0")
    monkeypatch.setenv("DBCTL_MODULES_BASE_REF", "origin/develop")
    monkeypatch.setenv("DBCTL_MODULES_IGNORE", "docs/**,*.md")
    cfg = load_config(tmp_config, tmp_config / ".dbctl.toml")
    assert cfg.modules.detect is False
    assert cfg.modules.install_new is False
    assert cfg.modules.base_ref == "origin/develop"
    assert cfg.modules.ignore == ["docs/**", "*.md"]


def test_seeds_path_resolved_from_root(tmp_config) -> None:
    (tmp_config / "temp" / "seeds").mkdir(parents=True)
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n' + '[seeds]\npath = "temp/seeds"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_config, tmp_config / ".dbctl.toml")
    assert cfg.seeds.configured is True
    assert cfg.seeds.path == (tmp_config / "temp" / "seeds").resolve()


def test_seeds_missing_dir_warns(tmp_config, capsys) -> None:
    (tmp_config / ".dbctl.toml").write_text(
        '[postgres]\ncontainer="c"\nuser="u"\npassword="p"\ntemplate_db="t"\n'
        '[odoo]\ncontainer="o"\ncompose_service="web"\n'
        + '[seeds]\npath = "temp/does-not-exist"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_config, tmp_config / ".dbctl.toml")
    assert cfg.seeds.path is not None
    assert any("does not exist" in w for w in cfg.warnings)


def test_compose_files_includes_existing_override(tmp_config) -> None:
    (tmp_config / "docker-compose.override.yaml").write_text("x\n", encoding="utf-8")
    cfg = load_config(tmp_config, tmp_config / ".dbctl.toml")
    assert cfg.compose_files == ["docker-compose.yml", "docker-compose.override.yaml"]
