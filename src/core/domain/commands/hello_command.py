"""
Hello command implementation.

This module provides the hello command, which displays a welcome banner.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class HelloCommand(BaseCommand):
    """Command to display a welcome banner."""

    name = "hello"
    format = "hello"
    description = "Return the interactive welcome banner"
    examples = ["!/hello"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """
        Execute the hello command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        # Create a new state with hello_requested=True
        from src.core.domain.session import SessionStateAdapter

        if isinstance(session, SessionStateAdapter):
            session.hello_requested = True

        return CommandResult(
            name=self.name,
            success=True,
            message="Hello, this is llm-interactive-proxy v0.1.0. How can I help you today?",
        )
