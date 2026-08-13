"""Strategy selection."""

from __future__ import annotations

from dbctl.config import Config
from dbctl.errors import ConfigError
from dbctl.strategies.base import Strategy
from dbctl.strategies.compose_override import ComposeOverrideStrategy
from dbctl.strategies.custom import CustomStrategy


def get_strategy(cfg: Config) -> Strategy:
    if cfg.strategy.kind == "compose-override":
        return ComposeOverrideStrategy(cfg)
    if cfg.strategy.kind == "custom":
        return CustomStrategy(cfg)
    raise ConfigError(
        f"unknown strategy kind '{cfg.strategy.kind}' (valid: compose-override, custom)"
    )
