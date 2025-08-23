"""
PWD command implementation.

This module provides the pwd command, which displays the current project directory.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class PwdCommand(StatelessCommandBase, BaseCommand):
    """Command to display the current project directory."""

    def __init__(self) -> None:
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "pwd"

    @property
    def format(self) -> str:
        return "pwd"

    @property
    def description(self) -> str:
        return "Display the current project directory"

    @property
    def examples(self) -> list[str]:
        return ["!/pwd"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """
        Execute the pwd command.

        Args:
            args: Command arguments
            session: The session

        Returns:
            The command result
        """
        project_dir = session.state.project_dir

        if project_dir:
            return CommandResult(name=self.name, success=True, message=project_dir)
        else:
            return CommandResult(
                name=self.name, success=True, message="Project directory not set"
            )
