"""Fixed command service with correct indentation."""

import asyncio
import json
import logging
import re
from typing import Any

from src.core.domain.chat import ChatMessage
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.session_service_interface import ISessionService


class CommandResultWrapper:
    """Wrapper for CommandResult to provide compatibility with both interfaces."""

    def __init__(self, result: CommandResult) -> None:
        """Initialize the wrapper.

        Args:
            result: A CommandResult
        """
        self.result = result

    @property
    def success(self) -> bool:
        return self.result.success

    @property
    def message(self) -> str:
        return self.result.message

    @property
    def new_state(self) -> Any | None:
        return self.result.new_state

    @property
    def data(self) -> dict[str, Any]:
        return self.result.data or {}

    @property
    def command(self) -> str:
        # Extract command name from CommandResult
        return self.result.name


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
    return re.compile(rf"{escaped_prefix}(\w+)(?:$$(.*?)$$)?")


class CommandRegistry:
    """Registry for command handlers."""

    def __init__(self) -> None:
        """Initialize the command registry."""
        self._commands: dict[str, BaseCommand] = {}
        # Static instance for bridging to non-DI code
        CommandRegistry._instance = self

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
            A dictionary of command name to handler
        """
        return self._commands.copy()

    def get_commands(self) -> dict[str, BaseCommand]:
        """Get all registered commands.

        Returns:
            A dictionary of command name to handler
        """
        return self.get_all()

    def get_handler(self, name: str) -> BaseCommand | None:
        """Get a command handler by name.

        Args:
            name: The name of the command

        Returns:
            The command handler or None if not found
        """
        return self.get(name)
    
    # Static instance for bridging
    _instance: "CommandRegistry | None" = None
    
    @staticmethod
    def get_instance() -> "CommandRegistry | None":
        """Get the global instance of the registry.

        This is a bridge for non-DI code to access the DI-registered commands.

        Returns:
            The global command registry instance or None if not initialized
        """
        return CommandRegistry._instance

    @staticmethod
    def set_instance(registry: "CommandRegistry") -> None:
        """Set the global instance of the registry.

        This is primarily for testing purposes to inject a specific registry instance.

        Args:
            registry: The registry instance to set as global
        """
        CommandRegistry._instance = registry

    @staticmethod
    def clear_instance() -> None:
        """Clear the global instance.

        This is primarily for testing purposes to reset the global state.
        """
        CommandRegistry._instance = None

    @staticmethod
    def ensure_instance() -> "CommandRegistry":
        """Ensure a global instance exists, creating one if necessary.

        This is useful for test scenarios where no DI container is available
        but we still need command functionality.

        Returns:
            The global command registry instance
        """
        if CommandRegistry._instance is None:
            logger.debug("Creating new command registry instance for testing")
            CommandRegistry._instance = CommandRegistry()
        return CommandRegistry._instance


class CommandService(ICommandService):
    """
    A service for processing and executing commands.
    """

    def __init__(
        self,
        command_registry: CommandRegistry,
        session_service: ISessionService,
        preserve_unknown: bool = False,
    ) -> None:
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

    async def register_command(self, command_name: str, command_handler: Any) -> None:
        """Register a command handler.

        Args:
            command_name: The name of the command
            command_handler: The command handler to register
        """
        self._registry.register(command_handler)

    async def process_commands(
        self, messages: list[ChatMessage], session_id: str
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

        session = (
            await self._session_service.get_session(session_id)
            if self._session_service
            else None
        )

        modified_messages = messages.copy()
        command_results = []
        command_executed = False

        for i in range(len(modified_messages) - 1, -1, -1):
            message = modified_messages[i]

            if message.role == "user":
                content = message.content or ""
                if isinstance(content, str):
                    if content.startswith("!/"):
                        match = re.match(r"!/(\w+)\(([^)]*)\)", content)
                        if match:
                            cmd_name = match.group(1)
                            args_str = match.group(2)
                            paren_start = content.find("(")
                            if paren_start != -1:
                                paren_end = content.find(")", paren_start)
                                if paren_end != -1:
                                    match_end = paren_end + 1
                                else:
                                    match_end = len(content)
                            else:
                                match_end = len(content)
                            remaining = content[
                                match_end:
                            ]
                        else:
                            match = re.match(r"!/(\w+)", content)
                            if match:
                                cmd_name = match.group(1)
                                args_str = None
                                match_end = match.end()
                                remaining = content[
                                    match_end:
                                ]
                            else:
                                continue

                        cmd = self._registry.get(cmd_name)

                        if cmd:
                            args = {}
                            if args_str:
                                try:
                                    args = json.loads(args_str)
                                    if not isinstance(args, dict):
                                        args = {"value": args}
                                except Exception:
                                    for arg in args_str.split(","):
                                        arg = arg.strip()
                                        if "=" in arg:
                                            key, value = arg.split("=", 1)
                                            val = value.strip()
                                            if (
                                                val.startswith('"')
                                                and val.endswith('"')
                                            ) or (
                                                val.startswith("'")
                                                and val.endswith("'")
                                            ):
                                                val = val[1:-1]
                                            args[key.strip()] = val
                                        elif arg:
                                            if ":" in arg or "/" in arg:
                                                args["element"] = arg
                                            else:
                                                args[arg] = True

                            if session is None:
                                logger.warning(
                                    f"Cannot execute command {cmd_name} without a session"
                                )
                                continue

                            logger.info(
                                f"Executing command: {cmd_name} with session: {session.session_id if session else 'N/A'}"
                            )

                            context = type(
                                "CommandContext",
                                (),
                                {"command_registry": self._registry},
                            )()

                            result: CommandResult
                            try:
                                coro_result = cmd.execute(args, session, context)
                                if asyncio.iscoroutine(coro_result):
                                    result = await coro_result
                                else:
                                    result = coro_result
                            except Exception:
                                result = await cmd.execute(args, session, context)

                            if (
                                (result.success or getattr(result, "new_state", None))
                                and self._session_service
                                and session
                            ):
                                if hasattr(result, "new_state") and result.new_state:
                                    logger.info(
                                        f"Updating session state with new_state from command: {result.new_state}"
                                    )
                                    try:
                                        session.update_state(result.new_state)
                                    except Exception:
                                        session.state = result.new_state
                                else:
                                    logger.info(
                                        "No new_state in command result, not updating session state"
                                    )
                                await self._session_service.update_session(session)
                                logger.info("Session updated in repository")

                            wrapped_result = CommandResultWrapper(result)
                            command_results.append(wrapped_result)
                            command_executed = True

                            if remaining:
                                modified_messages[i].content = " " + remaining.strip()
                            else:
                                modified_messages[i].content = ""
                        elif not self._preserve_unknown:
                            modified_messages[i].content = " "
                    break

        return ProcessedResult(
            modified_messages=modified_messages,
            command_executed=command_executed,
            command_results=command_results,
        )
