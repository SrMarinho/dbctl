"""Unit tests for dbctl.postgres: SQL quoting, guards, listing, clone."""

from __future__ import annotations

import pytest

from dbctl.errors import DatabaseError
from dbctl.postgres import (
    _ident,
    _lit,
    clone_database,
    create_database,
    database_exists,
    drop_database,
    installed_modules,
    list_databases,
    terminate_connections,
)


def test_ident_quotes_and_escapes() -> None:
    assert _ident("dev_a") == '"dev_a"'
    assert _ident('we"ird') == '"we""ird"'


def test_lit_quotes_and_escapes() -> None:
    assert _lit("dev_a") == "'dev_a'"
    assert _lit("it's") == "'it''s'"


def test_database_exists_true(fake_psql, make_config) -> None:
    fake_psql.on("SELECT 1 FROM pg_database", returns="1\n")
    assert database_exists(make_config(), "dev_x") is True


def test_database_exists_false(fake_psql, make_config) -> None:
    fake_psql.default = ""
    assert database_exists(make_config(), "dev_x") is False


def test_database_exists_quotes_literal(fake_psql, make_config) -> None:
    fake_psql.default = ""
    database_exists(make_config(), "dev_it's")
    sql = fake_psql.last()[-1]
    assert "datname = 'dev_it''s'" in sql


def test_database_exists_dry_run_assumes_true(make_config, monkeypatch) -> None:
    monkeypatch.setenv("DBCTL_DRY_RUN", "1")
    cfg = make_config()
    assert database_exists(cfg, "whatever") is True


def test_list_databases_filters_prefix(fake_psql, make_config) -> None:
    # The psql fake simulates the server: it already applied the LIKE filter.
    fake_psql.on("pg_database_size", returns="dev_a|12 MB\ndev_b|3 MB\n")
    rows = list_databases(make_config(), "dev_")
    assert rows == [("dev_a", "12 MB"), ("dev_b", "3 MB")]
    # The SQL itself must carry the prefix filter (defense in depth).
    sql = fake_psql.last()[-1]
    assert "LIKE" in sql and "dev\\_%" in sql


def test_list_databases_escapes_like_metachars(fake_psql, make_config) -> None:
    fake_psql.default = ""
    list_databases(make_config(), "dev_x_")
    sql = fake_psql.last()[-1]
    assert "dev\\_x\\_%" in sql  # '_' escaped so the prefix is literal


def test_terminate_connections(fake_psql, make_config) -> None:
    terminate_connections(make_config(), "dev_x")
    sql = fake_psql.last()[-1]
    assert "pg_terminate_backend" in sql
    assert "datname = 'dev_x'" in sql


def test_create_database_fresh(fake_psql, make_config) -> None:
    fake_psql.default = ""
    create_database(make_config(), "dev_x")
    sql = fake_psql.last()[-1]
    assert 'CREATE DATABASE "dev_x"' in sql
    assert "TEMPLATE" not in sql


def test_create_database_refuses_when_target_exists(fake_psql, make_config) -> None:
    fake_psql.on("SELECT 1 FROM pg_database", returns="1\n")
    with pytest.raises(DatabaseError, match="already exists"):
        create_database(make_config(), "dev_x")


def test_create_database_wraps_failure(fake_psql, make_config) -> None:
    fake_psql.default = ""
    fake_psql.fail_on("CREATE DATABASE", exit_code=1)
    with pytest.raises(DatabaseError, match="failed to create database 'dev_x'"):
        create_database(make_config(), "dev_x")


def test_clone_database(fake_psql, make_config) -> None:
    fake_psql.default = ""
    cfg = make_config()
    clone_database(cfg, "tpl", "dev_x")
    sql = fake_psql.last()[-1]
    assert 'CREATE DATABASE "dev_x" TEMPLATE "tpl"' in sql


def test_clone_refuses_when_target_exists(fake_psql, make_config) -> None:
    fake_psql.on("SELECT 1 FROM pg_database", returns="1\n")
    with pytest.raises(DatabaseError, match="already exists"):
        clone_database(make_config(), "tpl", "dev_x")


def test_clone_wraps_failure(fake_psql, make_config) -> None:
    fake_psql.default = ""
    fake_psql.fail_on("CREATE DATABASE", exit_code=1)
    with pytest.raises(DatabaseError, match="failed to clone"):
        clone_database(make_config(), "tpl", "dev_x")


def test_drop_database_prefix_guard(fake_psql, make_config) -> None:
    with pytest.raises(DatabaseError, match="does not start with db_prefix"):
        drop_database(make_config(), "other_db")


def test_drop_database_terminates_then_drops(fake_psql, make_config) -> None:
    fake_psql.default = ""
    drop_database(make_config(), "dev_x")
    sqls = [c[-1] for c in fake_psql.calls]
    assert any("pg_terminate_backend" in s for s in sqls)
    assert any('DROP DATABASE IF EXISTS "dev_x"' in s for s in sqls)


def test_installed_modules_parses(fake_psql, make_config) -> None:
    fake_psql.on("ir_module_module", returns="base\nsale\n")
    assert installed_modules(make_config(), "dev_x") == {"base", "sale"}


def test_installed_modules_non_odoo_returns_none(fake_psql, make_config) -> None:
    fake_psql.fail_on(
        "ir_module_module",
        exit_code=1,
        message="relation ir_module_module does not exist",
    )
    assert installed_modules(make_config(), "dev_x") is None
