"""Project discovery and git helpers.

Git is executed through docker.run (the single process-spawning wrapper),
so the "process calls only live in docker.py" rule stays intact.
"""

from __future__ import annotations

from pathlib import Path

from dbctl.docker import run
from dbctl.errors import DockerError, GitError, ProjectNotFoundError


def find_project_root(start: Path) -> Path:
    """Walk up from ``start`` looking for a .dbctl.toml file."""
    p = start.expanduser().resolve()
    if p.is_file():
        p = p.parent
    for candidate in (p, *p.parents):
        if (candidate / ".dbctl.toml").is_file():
            return candidate
    raise ProjectNotFoundError(
        f"no .dbctl.toml found from '{start}' up to '/'.\n"
        "To inject a project into dbctl: copy .dbctl.example.toml to "
        "<project>/.dbctl.toml, fill in the containers/credentials, and add "
        "'.dbctl.toml' to the project's .gitignore."
    )


def is_git_repo(root: Path) -> bool:
    try:
        run(["git", "-C", str(root), "rev-parse", "--git-dir"], capture=True)
        return True
    except DockerError:
        return False


def current_branch(root: Path) -> str:
    """Current branch name of the repository at ``root``.

    Raises GitError when the repo is missing or HEAD is detached (there is
    no branch to name the database).
    """
    if not is_git_repo(root):
        raise GitError(f"'{root}' is not a git repository - dbctl needs a branch name.")
    try:
        out = run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture=True,
        )
    except DockerError as exc:
        raise GitError(f"could not read the current branch in '{root}': {exc}") from exc
    branch = out.strip()
    if branch == "HEAD":
        raise GitError(
            "HEAD is detached - there is no branch to name the database.\n"
            "Run 'git checkout <branch>' first."
        )
    return branch


def working_tree_dirty(root: Path) -> bool:
    """True when the project has uncommitted changes (porcelain is non-empty)."""
    try:
        out = run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture=True,
        )
    except DockerError:
        return False
    return bool(out.strip())
