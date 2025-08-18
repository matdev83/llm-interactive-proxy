"""
Tool loop max repeats command implementation.

This module provides a domain command for setting tool loop max repeats.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionStateAdapter
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class ToolLoopMaxRepeatsCommand(BaseCommand):
    """Command for setting tool loop max repeats."""

    name = "tool-loop-max-repeats"
    format = "tool-loop-max-repeats([max_repeats=number])"
    description = "Set the maximum number of repeats for tool loop detection"
    examples = [
        "!/tool-loop-max-repeats(max_repeats=5)",
        "!/tool-loop-max-repeats(max_repeats=10)",
    ]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set tool loop max repeats.

        Args:
            args: Command arguments with max_repeats value
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        max_repeats = args.get("max_repeats")

        if max_repeats is None:
            return CommandResult(
                success=False, message="Max repeats must be specified", name=self.name
            )

        try:
            max_repeats_int = int(max_repeats)
            if max_repeats_int < 2:
                return CommandResult(
                    success=False,
                    message="Max repeats must be at least 2",
                    name=self.name,
                )
        except ValueError:
            return CommandResult(
                success=False,
                message="Max repeats must be a valid integer",
                name=self.name,
            )

        try:
            # Create updated session state with tool loop max repeats config
            updated_state: ISessionState

            if isinstance(session.state, SessionStateAdapter):
                # Working with SessionStateAdapter - get the underlying state
                old_state = session.state._state

                # Create new tool loop max repeats config
                loop_config = old_state.loop_config.with_tool_loop_max_repeats(
                    max_repeats_int
                )

                # Create new session state with updated tool loop max repeats config
                new_state = old_state.with_loop_config(loop_config)
                updated_state = SessionStateAdapter(new_state)
            else:
                # Fallback for other implementations
                updated_state = session.state

            return CommandResult(
                name=self.name,
                success=True,
                message=f"Tool loop max repeats set to {max_repeats_int}",
                data={"max_repeats": max_repeats_int},
                new_state=updated_state,
            )
        except Exception as e:
            logger.error(f"Error setting tool loop max repeats: {e}")
            return CommandResult(
                success=False,
                message=f"Error setting tool loop max repeats: {e}",
                name=self.name,
            )
