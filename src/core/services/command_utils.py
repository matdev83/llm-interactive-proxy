"""Utility functions and classes for command processing."""

import logging
import re

from src.core.domain.commands.base_command import BaseCommand

logger = logging.getLogger(__name__)


def get_command_pattern(command_prefix: str) -> re.Pattern:
    """Get regex pattern for detecting commands.

    Args:
        command_prefix: The command prefix to use

    Returns:
        A compiled regex pattern
    """
    # Escape special regex characters in the prefix
    escaped_prefix = re.escape(command_prefix)
    # Pattern to match commands with optional arguments in parentheses
    return re.compile(rf"{escaped_prefix}(?P<cmd>\w+)(?:\((?P<args>.*?)\))?")


class CommandRegistry:
    """Registry for command handlers."""

    def __init__(self) -> None:
        """Initialize the command registry."""
        self._commands: dict[str, BaseCommand] = {}

    def register(self, command: BaseCommand) -> None:
        """Register a command handler.

        Args:
            command: The command handler to register
        """
        # Validate that the command was created through proper DI
        command._validate_di_usage()

        self._commands[command.name] = command
        logger.info(f"Registered command: {command.name}")

    def get(self, name: str) -> BaseCommand | None:
        """Get a command handler by name.

        Args:
            name: The name of the command

        Returns:
            The command handler or None if not found
        """
        return self._commands.get(name)

    def get_all(self) -> dict[str, BaseCommand]:
        """Get all registered commands.

        Returns:
            Dictionary mapping command names to their handlers
        """
        return self._commands.copy()

    def list_commands(self) -> list[str]:
        """Get list of all registered command names.

        Returns:
            List of command names
        """
        return list(self._commands.keys())
