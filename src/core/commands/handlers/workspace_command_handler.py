"""
Workspace command handler for gemini-cli-acp backend.

This handler allows users to change the workspace directory for the gemini-cli-acp
backend at runtime using slash commands like !/workspace(/path/to/workspace).

The workspace directory is where the gemini-cli agent operates, and changing it
will restart the gemini-cli subprocess with the new workspace.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@command("workspace")
class WorkspaceCommandHandler(ICommandHandler):
    """Handler for the 'workspace' command to set gemini-cli-acp workspace."""

    @property
    def command_name(self) -> str:
        return "workspace"

    @property
    def description(self) -> str:
        return "Set the workspace directory for gemini-cli-acp backend"

    @property
    def format(self) -> str:
        return "!/workspace(path)"

    @property
    def examples(self) -> list[str]:
        return [
            "!/workspace(/home/user/project)",
            "!/workspace(C:\\Users\\username\\projects\\myproject)",
            "!/workspace(~/myproject)",
        ]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle workspace command by updating session state.

        Args:
            command: The parsed command with arguments
            session: The current session

        Returns:
            CommandResult indicating success/failure and updated state
        """
        # Get the path argument
        path = command.args.get("path")

        if not path:
            # If no path provided, show current workspace
            # Use project_dir from session state
            current_workspace = session.state.project_dir
            if current_workspace:
                return CommandResult(
                    success=True,
                    message=f"Current workspace: {current_workspace}",
                )
            else:
                return CommandResult(
                    success=True,
                    message="No workspace set (using backend default)",
                )

        # Validate and expand the path
        workspace_path = str(path)

        # Expand environment variables and user home shortcuts
        expanded_path = os.path.expanduser(os.path.expandvars(workspace_path))

        # Validate the directory exists
        if not os.path.isdir(expanded_path):
            return CommandResult(
                success=False,
                message=f"Workspace directory not found: {expanded_path}",
            )

        # Convert to absolute path
        absolute_path = str(Path(expanded_path).resolve())

        # Use project_dir to store workspace path
        # This is available via session.state.project_dir
        new_state = session.state.with_project_dir(absolute_path)

        logger.info(f"Workspace changed to: {absolute_path}")

        return CommandResult(
            success=True,
            message=f"Workspace set to: {absolute_path}",
            new_state=new_state,
        )
