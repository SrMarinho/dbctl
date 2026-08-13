"""Unit tests for dbctl.errors: stable exit codes per error class."""

from __future__ import annotations

from dbctl.errors import (
    ConfigError,
    DatabaseError,
    DbctlError,
    DockerError,
    GitError,
    ProjectNotFoundError,
    SeedError,
    UserAbort,
)

CASES = [
    (DbctlError, 1),
    (ProjectNotFoundError, 2),
    (ConfigError, 3),
    (GitError, 4),
    (DockerError, 5),
    (DatabaseError, 6),
    (SeedError, 7),
    (UserAbort, 130),
]


def test_exit_codes() -> None:
    for cls, code in CASES:
        assert cls.exit_code == code, f"{cls.__name__} should exit {code}"
        exc = cls("msg")
        assert str(exc) == "msg"
        assert exc.message == "msg"


def test_exit_codes_are_distinct() -> None:
    codes = [cls.exit_code for cls, _ in CASES]
    assert len(codes) == len(set(codes))
