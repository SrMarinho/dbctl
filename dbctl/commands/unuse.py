"""dbctl unuse - drop the override and return the project to its base config."""

from __future__ import annotations

from dbctl.config import Config
from dbctl.strategies import get_strategy


def run(cfg: Config) -> dict:
    strategy = get_strategy(cfg)
    removed = strategy.current_database() is not None
    strategy.unuse()
    return {"removed": removed, "override": cfg.strategy.override_file}
