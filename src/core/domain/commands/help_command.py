"""
Help command implementation.

This module provides the help command, which displays available commands or details for a specific command.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class HelpCommand(BaseCommand):
    """Command to display help information about available commands."""

    name = "help"
    format = "help(<command>)"
    description = "Show available commands or details for a single command"
    examples = ["!/help", "!/help(set)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """
        Execute the help command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        # Try to get the command registry from context first
        command_registry = None
        commands = {}

        if context and hasattr(context, "command_registry"):
            # Use registry from context (test environment)
            command_registry = context.command_registry
            commands = command_registry.get_commands()
        else:
            # Get the command registry from the service provider (normal environment)
            from src.core.services.command_service import CommandRegistry

            # Access the command registry
            if context and hasattr(context, "app"):
                service_provider = context.app.state.service_provider
                command_registry = service_provider.get_required_service(
                    CommandRegistry
                )
                commands = command_registry.get_commands()
            else:
                # Fallback if no context is provided
                from src.core.di.services import get_service_provider

                service_provider = get_service_provider()
                command_registry = service_provider.get_required_service(
                    CommandRegistry
                )
                commands = command_registry.get_commands()

        if args:
            # For help(command=model), we want to look up the "model" command
            # The args dict should have one key-value pair like {"command": "model"}
            # So we get the value, not the key
            cmd_name = None
            if len(args) == 1:
                # Check if the key is "command" and use its value
                key, value = next(iter(args.items()))
                if key == "command":
                    cmd_name = value
                else:
                    # Fallback: use the key as the command name
                    cmd_name = key
            else:
                # Multiple args, use the first key
                cmd_name = next(iter(args.keys())).lower()

            if cmd_name:
                cmd_name = cmd_name.lower()
                cmd_handler = command_registry.get_handler(cmd_name)

                if not cmd_handler:
                    return CommandResult(
                        name=self.name,
                        success=False,
                        message=f"unknown command: {cmd_name}",
                    )

                parts = [
                    f"Help for {cmd_handler.name}",
                    f"{cmd_handler.name} - {cmd_handler.description}",
                    f"format: {cmd_handler.format}",
                ]

                if hasattr(cmd_handler, "examples") and cmd_handler.examples:
                    parts.append("examples: " + "; ".join(cmd_handler.examples))

                return CommandResult(
                    name=self.name, success=True, message="; ".join(parts)
                )

        # List all available commands
        command_names = sorted(commands.keys())
        return CommandResult(
            name=self.name,
            success=True,
            message="Available commands: " + ", ".join(command_names),
        )
