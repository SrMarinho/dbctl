"""Escape hatch strategy: run the commands declared in [strategy.commands].

Placeholders available: {db}, {modules}, {project_root}. The tool does not
try to be clever: if the project declared a command, dbctl runs it. This is
what allows plugging in an Odoo that lives outside Docker without adding
code to the tool.
"""

from __future__ import annotations

from dbctl.docker import run
from dbctl.errors import ConfigError
from dbctl.strategies.base import Strategy


class CustomStrategy(Strategy):
    def _run(self, template: str | None, **placeholders: object) -> None:
        if not template:
            return
        filled = template.format(
            db=placeholders.get("db", ""),
            modules=placeholders.get("modules", ""),
            install=placeholders.get("install", ""),
            project_root=self.cfg.project_root,
        )
        run(["bash", "-c", filled], cwd=str(self.cfg.project_root))

    def start(self, db: str | None) -> None:
        if db is None:
            return  # nothing to do: base behavior is whatever the project does
        self._run(self.cfg.strategy.commands.start, db=db)

    def stop(self) -> None:
        self._run(self.cfg.strategy.commands.stop)

    def apply_schema(self, db: str, modules: list[str], install: list[str] | None = None) -> None:
        template = self.cfg.strategy.commands.upgrade
        if not template:
            raise ConfigError(
                "strategy.kind = 'custom' needs [strategy.commands].upgrade for 'dbctl upgrade'"
            )
        self._run(
            template,
            db=db,
            modules=",".join(modules),
            install=",".join(install or []),
        )

    def upgrade(self, db: str, modules: list[str], install: list[str] | None = None) -> None:
        # The declared upgrade command is the project's own full flow;
        # do not wrap it in stop/start.
        self.apply_schema(db, modules, install)

    def current_database(self) -> str | None:
        return None  # the tool cannot know what a custom strategy serves

    def unuse(self) -> None:
        pass  # nothing managed by dbctl to remove
