"""Fixed command service with correct indentation."""

import asyncio
import json
import logging
import re
from typing import Any

from src.core.domain.chat import ChatMessage, MessageContentPartText
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
    return re.compile(rf"{escaped_prefix}(?P<cmd>\w+)(?:\((?P<args>.*?)\))?")


class CommandRegistry:
    """Registry for command handlers."""

    def __init__(self) -> None:
        """Initialize the command registry."""
        self._commands: dict[str, BaseCommand] = {}
        # Maintain internal-only test hook; avoid bridging in production
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
        """Internal-only hook for tests to access a registry instance.

        Use DI to obtain the registry in application code.
        """
        return CommandRegistry._instance

    @staticmethod
    def set_instance(registry: "CommandRegistry") -> None:
        """Set the global instance (test-only)."""
        CommandRegistry._instance = registry

    @staticmethod
    def clear_instance() -> None:
        """Clear the global instance (test-only)."""
        CommandRegistry._instance = None

    @staticmethod
    def ensure_instance() -> "CommandRegistry":
        """Ensure a global instance exists (test-only)."""
        if CommandRegistry._instance is None:
            logger.debug("Creating new CommandRegistry instance for tests")
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
            if message.role != "user":
                continue

            content = message.content or ""

            # Case 1: plain text content
            if isinstance(content, str):
                text = content
                # Find command with optional args first
                args_match = re.search(r"!/(\w+)\(([^)]*)\)", text)
                simple_match = re.search(r"!/(\w+)", text) if not args_match else None
                match = args_match or simple_match
                if not match:
                    break

                cmd_name = match.group(1)
                args_str = match.group(2) if args_match else None
                before = text[: match.start()]
                after = text[match.end() :]
                remaining = after

                # Remove the command from message text
                message.content = before + remaining

                cmd = self._registry.get(cmd_name)
                if cmd:
                    args: dict[str, Any] = {}
                    if args_str:
                        try:
                            args = json.loads(args_str)
                            if not isinstance(args, dict):
                                args = {"value": args}
                        except Exception:
                            for arg in args_str.split(","):
                                arg = arg.strip()
                                if "=" in arg:
                                    k, v = arg.split("=", 1)
                                    v = v.strip()
                                    if (v.startswith('"') and v.endswith('"')) or (
                                        v.startswith("'") and v.endswith("'")
                                    ):
                                        v = v[1:-1]
                                    args[k.strip()] = v
                                elif arg:
                                    if ":" in arg or "/" in arg:
                                        args["element"] = arg
                                    else:
                                        args[arg] = True

                    if session is None:
                        logger.warning(
                            f"Cannot execute command {cmd_name} without a session"
                        )
                        break

                    result_coro = cmd.execute(
                        args,
                        session,
                        type(
                            "CommandContext", (), {"command_registry": self._registry}
                        )(),
                    )
                    result = (
                        await result_coro
                        if asyncio.iscoroutine(result_coro)
                        else result_coro
                    )

                    if (
                        (result.success or getattr(result, "new_state", None))
                        and self._session_service
                        and session
                    ):
                        if getattr(result, "new_state", None):
                            try:
                                session.update_state(result.new_state)
                            except Exception:
                                session.state = result.new_state
                        await self._session_service.update_session(session)

                    command_results.append(CommandResultWrapper(result))
                    command_executed = True

                    if remaining:
                        modified_messages[i].content = " " + remaining.strip()
                    else:
                        modified_messages[i].content = " "
                else:
                    # Unknown command
                    if not self._preserve_unknown:
                        modified_messages[i].content = " "
                    command_executed = True
                break

            # Case 2: multimodal content (list of parts)
            if isinstance(content, list) or isinstance(content, tuple):  # noqa: SIM101
                new_parts: list[Any] = []
                handled = False
                for part in content:
                    if handled:
                        new_parts.append(part)
                        continue
                    if hasattr(part, "text") and (
                        not hasattr(part, "type") or part.type == "text"
                    ):
                        text = getattr(part, "text", "") or ""
                        args_match = re.search(r"!/(\w+)\(([^)]*)\)", text)
                        simple_match = (
                            re.search(r"!/(\w+)", text) if not args_match else None
                        )
                        match = args_match or simple_match
                        if not match:
                            new_parts.append(part)
                            continue

                        cmd_name = match.group(1)
                        args_str = match.group(2) if args_match else None
                        before = text[: match.start()]
                        after = text[match.end() :]
                        updated_text = (before + after).strip()

                        cmd = self._registry.get(cmd_name)
                        if cmd:
                            multi_modal_args: dict[str, Any] = {}
                            if args_str:
                                try:
                                    multi_modal_args = json.loads(args_str)
                                    if not isinstance(multi_modal_args, dict):
                                        multi_modal_args = {"value": multi_modal_args}
                                except Exception:
                                    for arg in args_str.split(","):
                                        arg = arg.strip()
                                        if "=" in arg:
                                            k, v = arg.split("=", 1)
                                            v = v.strip()
                                            if (
                                                v.startswith('"') and v.endswith('"')
                                            ) or (
                                                v.startswith("'") and v.endswith("'")
                                            ):
                                                v = v[1:-1]
                                            multi_modal_args[k.strip()] = v
                                        elif arg:
                                            if ":" in arg or "/" in arg:
                                                multi_modal_args["element"] = arg
                                            else:
                                                multi_modal_args[arg] = True

                            if session is None:
                                logger.warning(
                                    f"Cannot execute command {cmd_name} without a session"
                                )
                                new_parts.append(part)
                            else:
                                result_coro = cmd.execute(
                                    multi_modal_args,
                                    session,
                                    type(
                                        "CommandContext",
                                        (),
                                        {"command_registry": self._registry},
                                    )(),
                                )
                                result = (
                                    await result_coro
                                    if asyncio.iscoroutine(result_coro)
                                    else result_coro
                                )
                                if (
                                    (
                                        result.success
                                        or getattr(result, "new_state", None)
                                    )
                                    and self._session_service
                                    and session
                                ):
                                    if getattr(result, "new_state", None):
                                        try:
                                            session.update_state(result.new_state)
                                        except Exception:
                                            session.state = result.new_state
                                    await self._session_service.update_session(session)

                                command_results.append(CommandResultWrapper(result))
                                command_executed = True
                                handled = True
                                if updated_text:
                                    new_parts.append(
                                        MessageContentPartText(
                                            type="text", text=updated_text
                                        )
                                    )
                        else:
                            # Unknown command in part
                            command_executed = True
                            handled = True
                            if updated_text:
                                new_parts.append(
                                    MessageContentPartText(
                                        type="text", text=updated_text
                                    )
                                )
                    else:
                        new_parts.append(part)

                message.content = new_parts
                if handled:
                    break

        return ProcessedResult(
            modified_messages=modified_messages,
            command_executed=command_executed,
            command_results=command_results,
        )
