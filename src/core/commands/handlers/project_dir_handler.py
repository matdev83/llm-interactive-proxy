"""
Project directory command handler for the SOLID architecture.

This module provides a command handler for setting the project directory.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class ProjectDirCommandHandler(BaseCommandHandler):
    """Handler for setting the project directory."""

    def __init__(self) -> None:
        """Initialize the project directory command handler."""
        super().__init__("project-dir")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["project_dir", "projectdir"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Set the current project directory"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/project-dir(/path/to/project)",
            "!/project-dir(C:\\Users\\username\\projects\\myproject)",
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the project directory.

        Args:
            param_value: The project directory path (None to unset)
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        # Handle unset case (None or empty value)
        if not param_value:
            # Create new state with project directory unset
            new_state = current_state.with_project_dir(None)
            return CommandHandlerResult(
                success=True, message="Project directory unset", new_state=new_state
            )

        # Get the directory path
        dir_path = str(param_value)

        # Validate the directory path
        if not os.path.isdir(dir_path):
            # Tests expect a specific error message phrasing
            return CommandHandlerResult(
                success=False, message=f"Directory '{dir_path}' not found."
            )

        # Create new state with updated project directory
        new_state = current_state.with_project_dir(dir_path)

        return CommandHandlerResult(
            success=True,
            # Tests expect the handler to be silent when called via unified set
            # handler, but when used directly they expect a user-visible
            # confirmation message. We return the full message here and let
            # callers decide to silence it.
            message=f"Project directory set to {dir_path}",
            new_state=new_state,
        )
