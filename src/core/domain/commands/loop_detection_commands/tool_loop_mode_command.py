from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session
from src.tool_call_loop.config import ToolLoopMode

logger = logging.getLogger(__name__)

class ToolLoopModeCommand(BaseCommand):
    """Command for setting tool loop mode."""

    name = "tool-loop-mode"
    format = "tool-loop-mode(mode=strict|relaxed|off)"
    description = "Set the mode for tool loop detection"
    examples = ["!/tool-loop-mode(mode=strict)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set tool loop mode."""
        mode_str = args.get("mode")

        if not mode_str:
            return CommandResult(success=False, message="Mode must be specified", name=self.name)

        try:
            mode = ToolLoopMode(str(mode_str).lower())
        except ValueError:
            valid_modes = ", ".join([e.value for e in ToolLoopMode])
            return CommandResult(
                success=False,
                message=f"Invalid mode '{mode_str}'. Valid modes: {valid_modes}",
                name=self.name,
            )

        try:
            loop_config = session.state.loop_config.with_tool_loop_mode(mode)
            updated_state = session.state.with_loop_config(loop_config)

            return CommandResult(
                name=self.name,
                success=True,
                message=f"Tool loop mode set to {mode.value}",
                data={"mode": mode.value},
                new_state=updated_state,
            )
        except Exception as e:
            logger.error(f"Error setting tool loop mode: {e}")
            return CommandResult(
                success=False, message=f"Error setting tool loop mode: {e}", name=self.name
            )