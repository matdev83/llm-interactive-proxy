"""
Project command implementation.

This module provides a domain command for setting the project name.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.constants import COMMAND_EXECUTION_ERROR
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class ProjectCommand(StatelessCommandBase, BaseCommand):
    """Command for setting the project name."""

    def __init__(self) -> None:
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "project"

    @property
    def format(self) -> str:
        return "project([name=project-name])"

    @property
    def description(self) -> str:
        return "Change the active project for LLM requests"

    @property
    def examples(self) -> list[str]:
        return ["!/project(name=my-project)", "!/project(name=work-project)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set the project name.

        Args:
            args: Command arguments with project name
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        project_name = args.get("name")
        if not project_name:
            return CommandResult(
                success=False, message="Project name must be specified", name=self.name
            )

        try:
            # Create new session state with updated project name
            updated_state = session.state.with_project(project_name)

            return CommandResult(
                name=self.name,
                success=True,
                message=f"Project changed to {project_name}",
                data={"project": project_name},
                new_state=updated_state,
            )
        except Exception as e:
            error_message = COMMAND_EXECUTION_ERROR.format(error=str(e))
            logger.error(error_message)
            return CommandResult(success=False, message=error_message, name=self.name)
