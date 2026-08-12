"""Typed exceptions with a stable exit code per error class.

The CLI catches DbctlError, prints `Error: <message>` on stderr and exits
with the matching code. No raw traceback leaks on expected errors; only
`--verbose` shows the full traceback.
"""


class DbctlError(Exception):
    """Base class for all expected dbctl failures."""

    exit_code = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProjectNotFoundError(DbctlError):
    """No .dbctl.toml found walking up from the working directory."""

    exit_code = 2


class ConfigError(DbctlError):
    """Configuration file invalid or incomplete."""

    exit_code = 3


class GitError(DbctlError):
    """Not a git repository, or HEAD is detached."""

    exit_code = 4


class DockerError(DbctlError):
    """A docker command failed, or a required container is missing."""

    exit_code = 5


class DatabaseError(DbctlError):
    """Database-level failure: already exists, missing, or clone failed."""

    exit_code = 6


class SeedError(DbctlError):
    """A seed script (or the sanitizer) failed inside Odoo."""

    exit_code = 7


class UserAbort(DbctlError):
    """The user answered "no" to an interactive confirmation."""

    exit_code = 130
