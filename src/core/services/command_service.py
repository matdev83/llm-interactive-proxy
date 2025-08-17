from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from src.commands.base import CommandResult as LegacyCommandResult
from src.core.domain.commands import BaseCommand, HelloCommand
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.session_service import ISessionService


class CommandResultWrapper:
    """Wrapper for CommandResult to provide compatibility with both interfaces."""

    def __init__(self, result):
        """Initialize the wrapper.

        Args:
            result: Either a legacy CommandResult or a new CommandResult
        """
        self.result = result

    @property
    def success(self):
        return getattr(self.result, "success", False)

    @property
    def message(self):
        return getattr(self.result, "message", None)

    @property
    def data(self):
        if isinstance(self.result, LegacyCommandResult):
            return {"name": self.result.name}
        return getattr(self.result, "data", {})


logger = logging.getLogger(__name__)


def get_command_pattern(command_prefix: str) -> re.Pattern:
    """Get regex pattern for detecting commands.

    Args:
        command_prefix: The prefix used for commands

    Returns:
        A compiled regex pattern
    """
    prefix_escaped = re.escape(command_prefix)
    # Updated regex to correctly handle commands with and without arguments.
    # - (?P<cmd>[\w-]+) captures the command name.
    # - (?:\s*\((?P<args>[^)]*)\))? is an optional non-capturing group for arguments.
    pattern_string = rf"{prefix_escaped}(?P<cmd>[\w-]+)" r"(?:\s*\((?P<args>[^)]*)\))?"
    return re.compile(pattern_string, re.VERBOSE)


class CommandRegistry:
    """Registry for command handlers."""

    def __init__(self):
        """Initialize the command registry."""
        self._commands: dict[str, BaseCommand] = {}

        # Register built-in commands
        self.register(HelloCommand())

    def register(self, command: BaseCommand) -> None:
        """Register a command.

        Args:
            command: The command to register
        """
        self._commands[command.name] = command
        logger.info(f"Registered command: {command.name}")

    def get(self, name: str) -> BaseCommand | None:
        """Get a command by name.

        Args:
            name: The name of the command

        Returns:
            The command handler or None if not found
        """
        return self._commands.get(name)

    def get_all(self) -> dict[str, BaseCommand]:
        """Get all registered commands.

        Returns:
            A dictionary of command name to handler
        """
        return dict(self._commands)


class CommandService(ICommandService):
    """
    A service for processing and executing commands.
    """

    def __init__(
        self,
        command_registry: CommandRegistry,
        session_service: ISessionService,
        preserve_unknown: bool = False,
    ):
        """
        Initialize the command service.

        Args:
            command_registry: The command registry to use
            session_service: The session service to use
            preserve_unknown: Whether to preserve unknown commands
        """
        self._registry = command_registry
        self._session_service = session_service
        self._preserve_unknown = preserve_unknown

    async def process_commands(
        self, messages: list[Any], session_id: str
    ) -> ProcessedResult:
        """
        Processes a list of messages to identify and execute commands.

        Args:
            messages: The list of messages to process.
            session_id: The ID of the session.

        Returns:
            A ProcessedResult object indicating the result of the command processing.
        """
        if not messages:
            return ProcessedResult(
                modified_messages=[], command_executed=False, command_results=[]
            )

        # Get the session
        session = (
            await self._session_service.get_session(session_id)
            if self._session_service
            else None
        )

        # Process each message
        modified_messages = messages.copy()
        command_results = []
        command_executed = False

        # Process only the first user message
        for i, message in enumerate(modified_messages):
            if message.get("role") == "user":
                content = message.get("content", "")
                if content and content.startswith("!/"):
                    # Extract command name and args
                    match = re.match(r"!/([\w-]+)(?:\s*\(([^)]*)\))?\s*(.*)", content)
                    if match:
                        cmd_name, args_str, remaining = match.groups()
                        cmd = self._registry.get(cmd_name)

                        if cmd:
                            # Parse args
                            args = {}
                            if args_str:
                                for arg in args_str.split(","):
                                    arg = arg.strip()
                                    if "=" in arg:
                                        # Handle key=value format (e.g., for set commands)
                                        key, value = arg.split("=", 1)
                                        args[key.strip()] = value.strip()
                                    elif (
                                        arg
                                    ):  # Handle parameter-only format (e.g., for unset commands)
                                        # For parameter-only args, set the value to True
                                        args[arg] = True

                            # Execute command
                            # All commands now receive Session objects
                            cmd_state_arg = session
                            logger.info(
                                f"Executing command: {cmd_name} with session: {session.session_id}"
                            )

                            # Handle both async and sync execute methods
                            if asyncio.iscoroutinefunction(cmd.execute):
                                result = await cmd.execute(args, cmd_state_arg, None)
                            else:
                                result = cmd.execute(args, cmd_state_arg, None)

                            # If command was successful and we have a session service, update the session
                            if result.success and self._session_service and session:
                                await self._session_service.update_session(session)

                            # Wrap the result for compatibility
                            result = CommandResultWrapper(result)
                            command_results.append(result)
                            command_executed = True

                            # Update message content
                            if remaining:
                                modified_messages[i]["content"] = (
                                    " " + remaining.strip()
                                )
                            else:
                                modified_messages[i]["content"] = ""
                        elif not self._preserve_unknown:
                            # Remove unknown command
                            content_without_cmd = content.replace(
                                f"!/{cmd_name}", "", 1
                            )
                            if args_str:
                                content_without_cmd = content_without_cmd.replace(
                                    f"({args_str})", "", 1
                                )
                            modified_messages[i]["content"] = (
                                " " + content_without_cmd.strip()
                            )
                break

        return ProcessedResult(
            modified_messages=modified_messages,
            command_executed=command_executed,
            command_results=command_results,
        )

    async def register_command(self, command_name: str, command_handler: Any) -> None:
        """
        Register a new command handler.

        Args:
            command_name: The name of the command to register
            command_handler: The handler object or function for the command
        """
        if hasattr(command_handler, "name"):
            self._registry.register(command_handler)
        else:
            # Create a wrapper command if the handler is a function
            from src.core.domain.commands import BaseCommand

            class DynamicCommand(BaseCommand):
                @property
                def name(self) -> str:
                    return command_name

                async def execute(self, *args: Any, **kwargs: Any) -> Any:
                    return await command_handler(*args, **kwargs)

            self._registry.register(DynamicCommand())
