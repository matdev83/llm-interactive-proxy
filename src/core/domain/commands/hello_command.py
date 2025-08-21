from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class HelloCommand(StatelessCommandBase, BaseCommand):
    """
    Domain command for handling the 'hello' command.
    It returns a welcome banner and sets a flag on the session state.
    """

    def __init__(self):
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "hello"

    @property
    def format(self) -> str:
        return "!/hello"

    @property
    def description(self) -> str:
        return "Return the interactive welcome banner"

    @property
    def examples(self) -> list[str]:
        return ["!/hello"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the hello command.

        Args:
            args: Command arguments (ignored for this command).
            session: The current session.
            context: Optional context (ignored for this command).

        Returns:
            The command result with a welcome message and updated state.
        """
        logger.debug("Executing HelloCommand")

        # The core logic is to set the hello_requested flag on the state.
        updated_state = session.state.with_hello_requested(True)

        return CommandResult(
            name=self.name,
            success=True,
            message="Welcome to LLM Interactive Proxy!\n\nAvailable commands:\n- !/help - Show help information\n- !/set(param=value) - Set a parameter value\n- !/unset(param) - Unset a parameter value",
            new_state=updated_state,
        )
