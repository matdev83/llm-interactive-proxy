from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class ToolLoopDetectionCommand(StatelessCommandBase, BaseCommand):
    """Command for enabling/disabling tool loop detection."""

    _TRUTHY_VALUES = {"true", "yes", "1", "on"}

    def __init__(self) -> None:
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "tool-loop-detection"

    @property
    def format(self) -> str:
        return "tool-loop-detection(enabled=true|false)"

    @property
    def description(self) -> str:
        return "Enable or disable tool loop detection for the current session"

    @property
    def examples(self) -> list[str]:
        return ["!/tool-loop-detection(enabled=true)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Enable or disable tool loop detection."""
        enabled = self._parse_enabled(args)

        try:
            loop_config = session.state.loop_config.with_tool_loop_detection_enabled(
                enabled
            )
            updated_state = session.state.with_loop_config(loop_config)

            return CommandResult(
                name=self.name,
                success=True,
                message=f"Tool loop detection {'enabled' if enabled else 'disabled'}",
                data={"enabled": enabled},
                new_state=updated_state,
            )
        except Exception as e:
            logger.error("Error toggling tool loop detection: %s", e, exc_info=True)
            return CommandResult(
                success=False,
                message=f"Error toggling tool loop detection: {e}",
                name=self.name,
            )

    def _parse_enabled(self, args: Mapping[str, Any]) -> bool:
        """Return the desired enabled flag from the provided arguments."""

        enabled_arg = args.get("enabled", "true")
        if isinstance(enabled_arg, bool):
            return enabled_arg

        value = str(enabled_arg).strip().lower()
        return value in self._TRUTHY_VALUES
