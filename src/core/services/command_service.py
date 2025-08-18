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

    def __init__(self, result: Any) -> None:
        """Initialize the wrapper.

        Args:
            result: Either a legacy CommandResult or a new CommandResult
        """
        self.result = result

    @property
    def success(self) -> bool:
        return getattr(self.result, "success", False)

    @property
    def message(self) -> str | None:
        return getattr(self.result, "message", None)

    @property
    def new_state(self) -> Any | None:
        return getattr(self.result, "new_state", None)

    @property
    def data(self) -> dict[str, Any]:
        # Legacy command result handling removed
        return getattr(self.result, "data", {})

    @property
    def command(self) -> str:
        # Extract command name from CommandResult
        if hasattr(self.result, "name"):
            return self.result.name
        # Fallback for legacy command results
        if hasattr(self.result, "cmd_name"):
            return self.result.cmd_name
        if hasattr(self.result, "command"):
            return self.result.command
        return "command"


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

    def register(self, command: BaseCommand) -> None:
        """Register a command handler.

        Args:
            command: The command handler to register
        """
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
        self,
        messages: list[ChatMessage],
        session_id: str
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
        for i in range(len(modified_messages) - 1, -1, -1):
            message = modified_messages[i]

            if message.role == "user":
                content = message.content or ""
                if isinstance(content, str):
                    if content.startswith("!/"):
                        # Extract command name and args
                        # Handle format: !/command(args) 
                        match = re.match(r"!/(\w+)\(([^)]*)\)", content)
                        if match:
                            cmd_name = match.group(1)
                            args_str = match.group(2)
                            # Find the end position after the closing parenthesis
                            paren_start = content.find('(')
                            if paren_start != -1:
                                paren_end = content.find(')', paren_start)
                                if paren_end != -1:
                                    match_end = paren_end + 1
                                else:
                                    match_end = len(content)
                            else:
                                match_end = len(content)
                            remaining = content[match_end:]  # Capture remaining content after command
                        else:
                            # Handle format: !/command (without parentheses)
                            match = re.match(r"!/(\w+)", content)
                            if match:
                                cmd_name = match.group(1)
                                args_str = None
                                match_end = match.end()
                                remaining = content[match_end:]  # Capture remaining content after command
                            else:
                                continue

                        cmd = self._registry.get(cmd_name)

                        if cmd:
                            # Parse args
                            args = {}
                            if args_str:
                                try:
                                    args = json.loads(args_str)
                                    # Normalize scalar JSON args (e.g. 0.6) to a dict
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

                            # Execute command
                            # Commands expect the session state (adapter or state object)
                            if session is None:
                                logger.warning(
                                    f"Cannot execute command {cmd_name} without a session"
                                )
                                continue

                            logger.info(
                                f"Executing command: {cmd_name} with session: {session.session_id if session else 'N/A'}"
                            )

                            # Create context with command registry for commands that need it
                            context = type(
                                "CommandContext",
                                (),
                                {"command_registry": self._registry},
                            )()

                            # Handle both async and sync execute methods
                            result: CommandResult
                            try:
                                coro_result = cmd.execute(args, session, context)
                                if asyncio.iscoroutine(coro_result):
                                    result = await coro_result
                                else:
                                    result = coro_result
                            except Exception:
                                # Fallback - this shouldn't happen but just in case
                                result = await cmd.execute(args, session, context)

                            # If command was successful and we have a session service, update the session
                            logger.info(
                                f"Command result - success: {result.success}, has new_state: {hasattr(result, 'new_state') and result.new_state is not None}"
                            )
                            # Persist session changes when the command either
                            # succeeded or returned a new_state (some handlers may
                            # return new_state even when reporting partial failure).
                            if (
                                (result.success or getattr(result, "new_state", None))
                                and self._session_service
                                and session
                            ):
                                if hasattr(result, "new_state") and result.new_state:
                                    logger.info(
                                        f"Updating session state with new_state from command: {result.new_state}"
                                    )
                                    # Prefer session.update_state which replaces the
                                    # stored state with the handler-provided one so
                                    # subsequent requests see the change.
                                    try:
                                        session.update_state(result.new_state)
                                    except Exception:
                                        # Best-effort: fall back to assigning
                                        session.state = result.new_state
                                else:
                                    logger.info(
                                        "No new_state in command result, not updating session state"
                                    )
                                await self._session_service.update_session(session)
                                logger.info("Session updated in repository")

                            # Wrap the result for compatibility
                            wrapped_result = CommandResultWrapper(result)
                            command_results.append(wrapped_result)
                            command_executed = True

                            # Update message content
                            if remaining:
                                modified_messages[i].content = " " + remaining.strip()
                            else:
                                modified_messages[i].content = ""
                        elif not self._preserve_unknown:
                            # Remove unknown command and set content to a single space
                            modified_messages[i].content = " "
                    break  # Only process the first user message

        return ProcessedResult(
            modified_messages=modified_messages,
            command_executed=command_executed,
            command_results=command_results,
        )