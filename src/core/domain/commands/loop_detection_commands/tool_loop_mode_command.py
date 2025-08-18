"""
Tool loop mode command implementation.

This module provides a domain command for setting tool loop mode.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionStateAdapter
from src.core.interfaces.domain_entities_interface import ISessionState
from src.tool_call_loop.config import ToolLoopMode

logger = logging.getLogger(__name__)


class ToolLoopModeCommand(BaseCommand):
    """Command for setting tool loop mode."""

    name = "tool-loop-mode"
    format = "tool-loop-mode([mode=strict|relaxed|off])"
    description = "Set the mode for tool loop detection"
    examples = [
        "!/tool-loop-mode(mode=strict)",
        "!/tool-loop-mode(mode=relaxed)",
        "!/tool-loop-mode(mode=off)",
    ]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set tool loop mode.

        Args:
            args: Command arguments with mode value
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        mode_str = args.get("mode")

        if mode_str is None:
            return CommandResult(
                success=False, message="Mode must be specified", name=self.name
            )

        try:
            mode = ToolLoopMode(mode_str.lower())
        except ValueError:
            return CommandResult(
                success=False,
                message=f"Invalid mode '{mode_str}'. Valid modes: strict, relaxed, off",
                name=self.name,
            )

        try:
            # Create updated session state with tool loop mode config
            updated_state: ISessionState

            if isinstance(session.state, SessionStateAdapter):
                # Working with SessionStateAdapter - get the underlying state
                old_state = session.state._state

                # Create new tool loop mode config
                loop_config = old_state.loop_config.with_tool_loop_mode(mode)

                # Create new session state with updated tool loop mode config
                new_state = old_state.with_loop_config(loop_config)
                updated_state = SessionStateAdapter(new_state)
            else:
                # Fallback for other implementations
                updated_state = session.state

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
                success=False,
                message=f"Error setting tool loop mode: {e}",
                name=self.name,
            )
