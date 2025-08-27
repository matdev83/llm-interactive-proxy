from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.core.commands.handlers.command_handler import ILegacyCommandHandler
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session


class LegacyHandlerCommandAdapter(BaseCommand):
    """Adapter that exposes an ILegacyCommandHandler as a BaseCommand.

    This enables gradual migration away from the legacy handler layer by
    registering adapters in places expecting BaseCommand while preserving
    behavior.
    """

    def __init__(self, inner: ILegacyCommandHandler) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return getattr(self._inner, "name", "").strip()

    @property
    def format(self) -> str:
        # Prefer explicit usage/format on legacy handler
        usage = getattr(self._inner, "usage", None)
        if isinstance(usage, str) and usage:
            return usage
        return f"{self.name}([args])"

    @property
    def description(self) -> str:
        desc = getattr(self._inner, "description", None)
        if isinstance(desc, str) and desc:
            return desc
        return f"Command handler for {self.name} command"

    def examples(self) -> list[str]:  # type: ignore[override]
        examples = getattr(self._inner, "examples", None)
        return list(examples) if isinstance(examples, list) else []

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        # Legacy expects dict[str, str]; coerce values to strings where needed
        legacy_args: dict[str, str] = {}
        for k, v in dict(args).items():
            legacy_args[str(k)] = v if isinstance(v, str) else str(v)
        return await self._inner.execute(legacy_args, session, context)
