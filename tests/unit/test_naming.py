"""Unit tests for dbctl.naming (spec V7-V9: deterministic, <= 63 chars)."""

from __future__ import annotations

from dbctl.naming import database_name, slugify


def test_slugify_basic() -> None:
    assert slugify("feature-x") == "feature_x"
    assert slugify("Feature X") == "feature_x"
    assert slugify("GC-629-mod-fatura") == "gc_629_mod_fatura"


def test_slugify_collapses_and_strips() -> None:
    assert slugify("a--b__c") == "a_b_c"
    assert slugify("--leading") == "leading"
    assert slugify("trailing--") == "trailing"


def test_slugify_empty() -> None:
    assert slugify("---") == ""
    assert slugify("") == ""


def test_database_name_deterministic() -> None:
    assert database_name("main", "dev_") == database_name("main", "dev_")


def test_database_name_starts_with_prefix() -> None:
    assert database_name("whatever", "dev_gc_").startswith("dev_gc_")


def test_database_name_never_exceeds_63_chars() -> None:
    long_branch = "GC-629-mod-fatura-notificacoes-fornecedor-nf-pendente-envio-sei" * 3
    name = database_name(long_branch, "dev_")
    assert len(name) <= 63
    assert name.startswith("dev_")


def test_database_name_distinct_for_distinct_branches() -> None:
    # Truncated slugs could collide; the digest must disambiguate (spec V9).
    a = database_name("branch-with-a-long-name-part-one-x", "dev_")
    b = database_name("branch-with-a-long-name-part-two-y", "dev_")
    assert a != b


def test_database_name_long_prefix_respected() -> None:
    # A prefix that alone would exceed 63 chars must still yield <= 63
    # (the digest survives; config already blocks this, defense in depth).
    name = database_name("main", "dev_gc_" * 11)  # 77 chars
    assert len(name) <= 63
    assert len(name.rsplit("_", 1)[1]) == 6  # digest suffix intact


def test_database_name_example_regression() -> None:
    # Real case from a production project (spec): 80+ char branch -> short name.
    branch = "GC-629-mod-fatura-notificacoes-fornecedor-nf-pendente-envio-sei"
    name = database_name(branch, "dev_")
    assert name == "dev_gc_629_mod_fatura_notificacoes_fornecedor_nf_pendent_61ec20"
    assert len(name) <= 63
    # The digest suffix is exactly 6 hex chars after the underscore.
    suffix = name.rsplit("_", 1)[1]
    assert len(suffix) == 6
    assert all(c in "0123456789abcdef" for c in suffix)
