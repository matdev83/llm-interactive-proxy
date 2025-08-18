"""
Project command implementation.

This module provides a domain command for setting the project name.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class ProjectCommand(BaseCommand):
    """Command for setting the project name."""

    name = "project"
    format = "project([name=project-name])"
    description = "Change the active project for LLM requests"
    examples = [
        "!/project(name=my-project)",
        "!/project(name=work-project)",
    ]

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
                success=False,
                message="Project name must be specified",
                name=self.name,
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
            logger.error(f"Error setting project: {e}")
            return CommandResult(
                success=False,
                message=f"Error setting project: {e}",
                name=self.name,
            )