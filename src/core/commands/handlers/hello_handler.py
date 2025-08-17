"""
Hello command handler.

This handler implements the hello command, which displays a welcome banner.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    CommandHandlerResult,
    ICommandHandler,
)
from src.core.domain.session import SessionState

logger = logging.getLogger(__name__)


class HelloCommandHandler(ICommandHandler):
    """Handler for the hello command."""

    @property
    def name(self) -> str:
        """The name of the command."""
        return "hello"

    @property
    def aliases(self) -> list[str]:
        """Aliases for the command."""
        return []

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Return the interactive welcome banner"

    @property
    def usage(self) -> str:
        """Usage information for the command."""
        return "hello"

    @property
    def examples(self) -> list[str]:
        """Examples of command usage."""
        return ["!/hello"]

    def can_handle(self, command_name: str) -> bool:
        """Check if this handler can handle the given command.

        Args:
            command_name: The name of the command to check

        Returns:
            True if this handler can handle the command, False otherwise
        """
        command_lower = command_name.lower()
        return command_lower == self.name or command_lower in self.aliases

    def handle(
        self, command_name: str, args: dict[str, Any], state: SessionState
    ) -> CommandHandlerResult:
        """Handle the hello command.

        Args:
            command_name: The name of the command to handle
            args: Command arguments
            state: Current session state

        Returns:
            Command execution result
        """
        # Create a new session state with hello_requested=True
        new_state = SessionState(
            backend_config=state.backend_config,
            reasoning_config=state.reasoning_config,
            loop_config=state.loop_config,
            project=state.project,
            project_dir=state.project_dir,
            interactive_just_enabled=state.interactive_just_enabled,
            hello_requested=True,
            is_cline_agent=state.is_cline_agent,
        )

        return CommandHandlerResult(
            success=True,
            message="hello acknowledged",
            new_state=new_state,
        )
