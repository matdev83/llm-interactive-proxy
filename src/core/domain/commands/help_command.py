from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class HelpCommand(StatelessCommandBase, BaseCommand):
    """Command to display help information about available commands."""

    def __init__(self):
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "help"

    @property
    def format(self) -> str:
        return "help(<command>)"

    @property
    def description(self) -> str:
        return "Show available commands or details for a single command"

    @property
    def examples(self) -> list[str]:
        return ["!/help", "!/help(set)"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the help command.

        Args:
            args: Command arguments.
            session: The current session.
            context: Optional context, expected to contain 'handlers'.

        Returns:
            The command result.
        """
        handlers = context.get("handlers", {}) if context else {}

        # Case 1: Help for a specific command, e.g., !/help(set)
        if args:
            cmd_name = next(iter(args.keys()), None)
            if not cmd_name:
                return CommandResult(
                    success=False,
                    message="Invalid format for help command.",
                    name=self.name,
                )

            cmd_handler = handlers.get(cmd_name.lower())

            if not cmd_handler:
                return CommandResult(
                    name=self.name,
                    success=False,
                    message=f"Unknown command: {cmd_name}",
                )

            parts = [
                f"{cmd_handler.name} - {cmd_handler.description}",
                f"Format: {cmd_handler.format}",
            ]
            if cmd_handler.examples:
                parts.append("Examples: " + ", ".join(cmd_handler.examples))

            return CommandResult(name=self.name, success=True, message="\n".join(parts))

        # Case 2: List all available commands
        if not handlers:
            return CommandResult(
                name=self.name, success=True, message="No commands available."
            )

        command_lines = [
            f"- {name} - {cmd.description}" for name, cmd in sorted(handlers.items())
        ]
        message = "Available commands:\n" + "\n".join(command_lines)
        return CommandResult(name=self.name, success=True, message=message)
