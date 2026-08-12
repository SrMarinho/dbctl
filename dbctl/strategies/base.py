"""Strategy interface: how dbctl starts/stops/upgrades the Odoo service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from dbctl.config import Config


class Strategy(ABC):
    """Abstract strategy for driving the injected project's Odoo service."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @abstractmethod
    def start(self, db: str | None) -> None:
        """Serve ``db``; ``None`` means "back to the base config"."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the Odoo service."""

    @abstractmethod
    def upgrade(self, db: str, modules: list[str]) -> None:
        """Apply module upgrades (-u) to ``db`` and serve it again."""

    @abstractmethod
    def current_database(self) -> str | None:
        """Database currently served by the strategy, or None."""

    @abstractmethod
    def unuse(self) -> None:
        """Return to the base project config without touching the service."""
