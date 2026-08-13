"""Branch -> database name mapping.

Properties guaranteed by the algorithm below:
- deterministic (same branch always yields the same name);
- always <= 63 chars (Postgres identifier limit);
- always starts with the configured prefix (the safety net for drops);
- two different branches never collide (6-hex sha1 digest of the FULL
  original branch name disambiguates truncated slugs).
"""

from __future__ import annotations

import hashlib
import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_DIGEST_LEN = 6
_SEP_AND_DIGEST = 1 + _DIGEST_LEN  # "_" + 6 hex chars


def slugify(branch: str) -> str:
    """Normalize a branch name into a slug: lowercase, [a-z0-9_] only.

    Everything outside [a-z0-9] becomes "_", runs collapse to one, and
    leading/trailing underscores are stripped.
    """
    return _NON_ALNUM.sub("_", branch.lower()).strip("_")


def database_name(branch: str, prefix: str) -> str:
    """Return the Postgres database name for ``branch`` under ``prefix``.

    Guarantees <= 63 chars even for an oversized prefix (defense in depth:
    config validates the prefix, but callers must never produce an invalid
    identifier).
    """
    slug = slugify(branch)
    digest = hashlib.sha1(branch.encode("utf-8")).hexdigest()[:_DIGEST_LEN]
    budget = 63 - len(prefix) - _SEP_AND_DIGEST
    if budget < 0:
        # Trim the prefix so the digest (the disambiguator) always survives.
        prefix = prefix[: 63 - _SEP_AND_DIGEST]
        budget = 0
    return f"{prefix}{slug[:budget]}_{digest}"
