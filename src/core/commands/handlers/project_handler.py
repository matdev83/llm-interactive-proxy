"""
Project handler for the set command.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.constants.command_output_constants import (
    PROJECT_SET_MESSAGE,
    PROJECT_UNSET_MESSAGE,
)
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class ProjectCommandHandler(BaseCommandHandler):
    """Handler for the project parameter."""

    def __init__(self) -> None:
        super().__init__(name="project", aliases=["project-name"])

    @property
    def description(self) -> str:
        return "Set the current project name"

    @property
    def examples(self) -> list[str]:
        return ["!/set(project=my-project)"]

    def handle(
        self, param_value: Any, current_state: ISessionState, context: Any = None
    ) -> CommandHandlerResult:
        """Handle the project parameter.

        Args:
            param_value: The parameter value
            current_state: The current session state
            context: Optional context

        Returns:
            Result of handling the parameter
        """
        # If no value provided, treat this as an unset request
        if param_value is None:
            updated_state = current_state.with_project(None)
            return CommandHandlerResult(
                success=True, message=PROJECT_UNSET_MESSAGE, new_state=updated_state
            )

        project_name = str(param_value)

        # Update the state with the new project name
        updated_state = current_state.with_project(project_name)

        return CommandHandlerResult(
            success=True,
            message=PROJECT_SET_MESSAGE.format(project=project_name),
            new_state=updated_state,
        )
