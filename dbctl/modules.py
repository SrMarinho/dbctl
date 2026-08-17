"""Path -> Odoo module mapping for change detection.

What this branch changed since the base ref is exactly what needs `-u` on
its database (the branch DB is a clone of the template, which mirrors the
base branch). Detection is agnostic of layout: the module root is any
directory holding the manifest file (configurable, default
__manifest__.py), found by walking up from each changed file.
"""

from __future__ import annotations

import re
from pathlib import Path

from dbctl.config import Config
from dbctl.project import changed_paths, default_base_ref, merge_base


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob (with ** support) into an anchored regex.

    `**` matches across directory separators (`**/x` = x at any depth),
    `*` matches within a single segment, `?` matches one character.
    """
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")  # "**/" -> zero or more dirs
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def _ignored(path: str, patterns: list[str]) -> bool:
    return any(_glob_to_regex(pattern).match(path) for pattern in patterns)


def module_of(path: str, root: Path, manifest: str) -> str | None:
    """Name of the module containing ``path``, or None (unmatched).

    Walks up from the file's directory looking for a directory that holds
    the manifest; that directory's name is the module. Stops at the
    repository root.
    """
    current = (root / path).parent
    while True:
        if (current / manifest).is_file():
            return current.name
        if current == root:
            return None
        current = current.parent


def detect(cfg: Config) -> dict:
    """Detect modules changed on this branch since the base ref.

    Returns {base_ref, base_sha, modules, excluded, changed_paths, unmatched}.
    ``unmatched`` (files outside any module, e.g. docker-compose.yml) is
    useful only under --verbose; everything else ignores it. ``excluded`` is
    modules that changed but are listed in [modules].exclude - a project-wide
    escape hatch for a module that is broken independently of any branch
    (e.g. missing manifest dependency), so it never blocks `upgrade`/`create`
    for unrelated work. They are reported, never applied.
    """
    root = cfg.project_root
    base_ref = default_base_ref(root, cfg.modules.base_ref)
    base_sha = merge_base(root, base_ref)
    paths = [
        path for path in changed_paths(root, base_sha) if not _ignored(path, cfg.modules.ignore)
    ]
    exclude = set(cfg.modules.exclude)
    modules: list[str] = []
    excluded: list[str] = []
    unmatched: list[str] = []
    for path in paths:
        module = module_of(path, root, cfg.modules.manifest)
        if module is None:
            unmatched.append(path)
        elif module in exclude:
            if module not in excluded:
                excluded.append(module)
        elif module not in modules:
            modules.append(module)
    modules.sort()
    excluded.sort()
    return {
        "base_ref": base_ref,
        "base_sha": base_sha,
        "modules": modules,
        "excluded": excluded,
        "changed_paths": paths,
        "unmatched": unmatched,
    }
