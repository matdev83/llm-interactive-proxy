"""
Tool loop detection command implementation.

This module provides a domain command for enabling/disabling tool loop detection.
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


class ToolLoopDetectionCommand(BaseCommand):
    """Command for enabling/disabling tool loop detection."""

    name = "tool-loop-detection"
    format = "tool-loop-detection([enabled=true|false])"
    description = "Enable or disable tool loop detection for the current session"
    examples = [
        "!/tool-loop-detection(enabled=true)",
        "!/tool-loop-detection(enabled=false)",
        "!/tool-loop-detection()",
    ]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Enable or disable tool loop detection.

        Args:
            args: Command arguments with enabled flag
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        enabled = args.get("enabled", True)  # Default to enabled if not specified

        try:
            # Create updated session state with tool loop detection config
            updated_state: ISessionState

            if isinstance(session.state, SessionStateAdapter):
                # Working with SessionStateAdapter - get the underlying state
                old_state = session.state._state

                # Create new tool loop detection config
                loop_config = old_state.loop_config.with_tool_loop_detection_enabled(
                    enabled
                )

                # Create new session state with updated tool loop detection config
                new_state = old_state.with_loop_config(loop_config)
                updated_state = SessionStateAdapter(new_state)
            else:
                # Fallback for other implementations
                updated_state = session.state

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
