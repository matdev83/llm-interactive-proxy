from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class ToolLoopDetectionCommand(BaseCommand):
    """Command for enabling/disabling tool loop detection."""

    name = "tool-loop-detection"
    format = "tool-loop-detection(enabled=true|false)"
    description = "Enable or disable tool loop detection for the current session"
    examples = ["!/tool-loop-detection(enabled=true)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Enable or disable tool loop detection."""
        enabled_arg = args.get("enabled", "true")
        enabled = str(enabled_arg).lower() in ("true", "yes", "1", "on")

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
            logger.error(f"Error toggling tool loop detection: {e}")
            return CommandResult(
                success=False,
                message=f"Error toggling tool loop detection: {e}",
                name=self.name,
            )
