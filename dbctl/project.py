"""Project discovery, git helpers and config-file search.

Git is executed through docker.run (the single process-spawning wrapper),
so the "process calls only live in docker.py" rule stays intact.

The .dbctl.toml does NOT have to sit at the repository root (spec 5.0):
project_root (the git top-level) and the config file path are two distinct
concepts. All relative paths in the config resolve against project_root.
"""

from __future__ import annotations

from pathlib import Path

from dbctl.docker import run
from dbctl.errors import ConfigError, DockerError, GitError, ProjectNotFoundError

_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
_MAX_DEPTH = 3


def project_root(start: Path) -> Path:
    """Git top-level of the repository containing ``start``.

    Raises GitError when ``start`` is not inside a git repository.
    """
    p = start.expanduser().resolve()
    if p.is_file():
        p = p.parent
    try:
        out = run(["git", "-C", str(p), "rev-parse", "--show-toplevel"], capture=True)
    except DockerError as exc:
        raise GitError(
            f"'{p}' is not inside a git repository - dbctl needs one for the "
            "branch name and the config discovery."
        ) from exc
    return Path(out.strip())


def _prune(name: str) -> bool:
    return name in _SKIP_DIRS or name.startswith(".")


def _walk_down(directory: Path, depth: int, found: list[Path]) -> None:
    """Depth-first search for .dbctl.toml, max depth 3, pruned dirs."""
    candidate = directory / ".dbctl.toml"
    if candidate.is_file():
        found.append(candidate.resolve())
    if depth >= _MAX_DEPTH:
        return
    for child in sorted(directory.iterdir()):
        if child.is_dir() and not _prune(child.name):
            _walk_down(child, depth + 1, found)


def find_config(
    start: Path,
    explicit: Path | None = None,
    root_override: Path | None = None,
) -> tuple[Path, Path]:
    """Locate the .dbctl.toml and the project root (spec 5.0).

    Returns ``(config_path, project_root)``. Discovery order:
      1. ``explicit`` (--config / DBCTL_CONFIG) - skips all search;
      2. walking UP from ``start`` to the repository top;
      3. walking DOWN from the top, max depth 3, pruning heavy/dot dirs.

    Zero results -> ProjectNotFoundError. More than one -> ConfigError
    listing every candidate (ambiguity is never resolved silently).
    """
    if explicit is not None:
        cfg_path = explicit.expanduser().resolve()
        if not cfg_path.is_file():
            raise ConfigError(
                f"config file does not exist: {cfg_path} "
                "(from --config or DBCTL_CONFIG)"
            )
        if root_override is not None:
            return cfg_path, root_override.expanduser().resolve()
        return cfg_path, project_root(cfg_path.parent)

    p = start.expanduser().resolve()
    if p.is_file():
        p = p.parent
    top = root_override.expanduser().resolve() if root_override else project_root(p)

    candidates: list[Path] = []
    cur = p
    while True:
        candidate = cur / ".dbctl.toml"
        if candidate.is_file() and candidate.resolve() not in candidates:
            candidates.append(candidate.resolve())
        if cur == top:
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    _walk_down(top, 0, candidates)
    candidates = list(dict.fromkeys(candidates))  # dedupe (root found twice)

    if not candidates:
        raise ProjectNotFoundError(
            f"no .dbctl.toml found searching from '{start}' (up to the repo "
            "top and down from it, max depth 3).\n"
            "To inject a project into dbctl: copy .dbctl.example.toml into the "
            "repository (root or an already-ignored folder like temp/), fill in "
            "the containers/credentials, and check 'dbctl status'.\n"
            "You can also point dbctl at a specific file with "
            "--config PATH or DBCTL_CONFIG."
        )
    if len(candidates) > 1:
        listed = "\n".join(f"  - {c}" for c in candidates)
        raise ConfigError(
            f"more than one .dbctl.toml found in the repository:\n{listed}\n"
            "The database the Odoo instance serves depends on which file is "
            "read, so dbctl never picks silently. Choose one with "
            "--config PATH or DBCTL_CONFIG."
        )
    return candidates[0], top


def hooks_dir(root: Path) -> Path:
    """Effective hooks directory of the repository (spec: `--git-path hooks`).

    Respects a custom core.hooksPath, unlike assembling <root>/.git/hooks by
    hand. Raises GitError when ``root`` is not a git repository.
    """
    try:
        out = run(
            ["git", "-C", str(root), "rev-parse", "--git-path", "hooks"],
            capture=True,
        )
    except DockerError as exc:
        raise GitError(f"'{root}' is not a git repository: {exc}") from exc
    path = Path(out.strip())
    return path if path.is_absolute() else root / path


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
