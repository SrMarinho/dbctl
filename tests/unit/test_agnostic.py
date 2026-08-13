"""Agnosticism regression (spec V35): zero project-specific strings in dbctl/.

The tool must never hardcode anything from a real injected project. The
reviewer greps for these tokens; the test enforces the same invariant.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FORBIDDEN = ["credsus", "greencompras", "green-compras", "foo-user", "faturamento"]


def test_no_project_specific_strings_in_tool() -> None:
    sources = list((ROOT / "dbctl").rglob("*.py"))
    assert sources, "no sources found to scan"
    for path in sources:
        text = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN:
            assert token not in text, f"'{token}' leaked into {path.relative_to(ROOT)}"


def test_no_project_specific_strings_in_tests() -> None:
    sources = [
        p
        for p in (ROOT / "tests").rglob("*.py")
        if p.name != "test_agnostic.py"  # this file lists the forbidden tokens
    ]
    for path in sources:
        text = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN:
            assert token not in text, f"'{token}' leaked into {path.relative_to(ROOT)}"
