from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands import (
    BaseCommand,
    CreateFailoverRouteCommand,
    DeleteFailoverRouteCommand,
    HelloCommand,
    HelpCommand,
    ListFailoverRoutesCommand,
    OneoffCommand,
    RouteAppendCommand,
    RouteClearCommand,
    RouteListCommand,
    RoutePrependCommand,
)
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.session_service import ISessionService


class CommandResultWrapper:
    """Wrapper for CommandResult to provide compatibility with both interfaces."""

    def __init__(self, result: Any):
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
    pattern_string = rf"{prefix_escaped}(?P<cmd>[\w-]+)(?:\((?P<args>.*)\))?"
    return re.compile(pattern_string)


class CommandRegistry:
    """Registry for command handlers."""

    def __init__(self) -> None:
        """Initialize the command registry."""
        self._commands: dict[str, BaseCommand] = {}

        # Register built-in commands
        self.register(HelloCommand())
        self.register(HelpCommand())
        self.register(OneoffCommand())

        # Register failover commands
        self.register(CreateFailoverRouteCommand())
        self.register(DeleteFailoverRouteCommand())
        self.register(ListFailoverRoutesCommand())
        self.register(RouteAppendCommand())
        self.register(RoutePrependCommand())
        self.register(RouteListCommand())
        self.register(RouteClearCommand())

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
        for i in range(len(modified_messages) - 1, -1, -1):
            message = modified_messages[i]
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
                                        val = value.strip()
                                        # Strip surrounding quotes if present
                                        if (val.startswith('"') and val.endswith('"')) or (
                                            val.startswith("'") and val.endswith("'")
                                        ):
                                            val = val[1:-1]
                                        args[key.strip()] = val
                                    elif arg:
                                        # If argument looks like a backend:model or backend/model
                                        # (contains ':' or '/'), map it to the conventional
                                        # parameter name 'element' used by failover handlers.
                                        if ":" in arg or "/" in arg:
                                            args["element"] = arg
                                        else:
                                            # For parameter-only args that are flags, set True
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

                            # Handle both async and sync execute methods
                            result: CommandResult
                            try:
                                coro_result = cmd.execute(args, session, None)
                                if asyncio.iscoroutine(coro_result):
                                    result = await coro_result
                                else:
                                    result = coro_result
                            except Exception:
                                # Fallback - this shouldn't happen but just in case
                                result = await cmd.execute(args, session, None)

                            # If command was successful and we have a session service, update the session
                            logger.info(
                                f"Command result - success: {result.success}, has new_state: {hasattr(result, 'new_state') and result.new_state is not None}"
                            )
                            # Persist session changes when the command either
                            # succeeded or returned a new_state (some handlers may
                            # return new_state even when reporting partial failure).
                            if (result.success or getattr(result, "new_state", None)) and self._session_service and session:
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
                name: str = command_name

                async def execute(self, *args: Any, **kwargs: Any) -> Any:
                    return await command_handler(*args, **kwargs)

            self._registry.register(DynamicCommand())
