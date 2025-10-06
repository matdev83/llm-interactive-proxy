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

    # NOTE: Legacy static instance access has been removed.
    # All command registry access should use proper DI via ICommandRegistry interface.


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

        # Only process commands from the last user message
        last_user_message_index = -1
        for i in range(len(modified_messages) - 1, -1, -1):
            if modified_messages[i].role == "user":
                last_user_message_index = i
                break

        if last_user_message_index == -1:
            return ProcessedResult(
                modified_messages=modified_messages,
                command_executed=False,
                command_results=[]
            )

        message = modified_messages[last_user_message_index]
        content = message.content or ""

        # Case 1: plain text content
        if isinstance(content, str):
            text = content.rstrip()  # Remove trailing whitespace/newlines

            # Check if command is at the end of the text
            # Find command with optional args first
            args_match = re.search(r"!/(\w+)\(([^)]*)\)", text)
            simple_match = re.search(r"!/(\w+)", text) if not args_match else None
            match = args_match or simple_match

            # Only process if command is at the end of the text (after trimming)
            if not match or match.end() != len(text):
                return ProcessedResult(
                    modified_messages=modified_messages,
                    command_executed=False,
                    command_results=[]
                )

            cmd_name = match.group(1)
            args_str = match.group(2) if args_match else None
            before = text[: match.start()]
            after = text[match.end() :]
            remaining = after

            # Remove the command from message text
            message.content = before + remaining

            # Store the before content for later use
            before_content = before

            if cmd:
                args: dict[str, Any] = {}
                if args_str:
                    try:
                        args = json.loads(args_str)
                        if not isinstance(args, dict):
                            args = {"value": args}
                    except json.JSONDecodeError:
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
                    return ProcessedResult(
                        modified_messages=modified_messages,
                        command_executed=False,
                        command_results=[]
                    )

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
                        except (AttributeError, TypeError) as e:
                            # Fallback to direct state assignment; log for visibility
                            logger.debug(
                                "Session.update_state failed, assigning state directly: %s",
                                e,
                                exc_info=True,
                            )
                            session.state = result.new_state
                    await self._session_service.update_session(session)

                command_results.append(CommandResultWrapper(result))
                command_executed = True

                if remaining:
                    modified_messages[last_user_message_index].content = (
                        before_content + remaining.strip()
                    )
                else:
                    modified_messages[last_user_message_index].content = before_content
            else:
                # Unknown command
                if not self._preserve_unknown:
                    modified_messages[last_user_message_index].content = before_content
                command_executed = True

        # Case 2: multimodal content (list of parts)
        elif isinstance(content, list) or isinstance(content, tuple):
            # Check if the last text part has a command at the end
            last_text_part_index = -1
            last_text_part_content = ""

            for part_idx in range(len(content) - 1, -1, -1):
                part = content[part_idx]
                if hasattr(part, "text") and (
                    not hasattr(part, "type") or part.type == "text"
                ):
                    text = getattr(part, "text", "") or ""
                    if text.strip():  # Only consider non-empty text parts
                        last_text_part_index = part_idx
                        last_text_part_content = text.rstrip()
                        break

            if last_text_part_index == -1:
                return ProcessedResult(
                    modified_messages=modified_messages,
                    command_executed=False,
                    command_results=[]
                )

            # Check if command is at the end of the last text part
            args_match = re.search(r"!/(\w+)\(([^)]*)\)", last_text_part_content)
            simple_match = re.search(r"!/(\w+)", last_text_part_content) if not args_match else None
            match = args_match or simple_match

            # Only process if command is at the end of the text (after trimming)
            if not match or match.end() != len(last_text_part_content):
                return ProcessedResult(
                    modified_messages=modified_messages,
                    command_executed=False,
                    command_results=[]
                )

            cmd_name = match.group(1)
            args_str = match.group(2) if args_match else None
            before = last_text_part_content[: match.start()]
            after = last_text_part_content[match.end() :]
            updated_text = (before + after).strip()

            cmd = self._registry.get(cmd_name)
            if cmd:
                multi_modal_args: dict[str, Any] = {}
                if args_str:
                    try:
                        multi_modal_args = json.loads(args_str)
                        if not isinstance(multi_modal_args, dict):
                            multi_modal_args = {"value": multi_modal_args}
                    except json.JSONDecodeError:
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
                    return ProcessedResult(
                        modified_messages=modified_messages,
                        command_executed=False,
                        command_results=[]
                    )
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
                            except (AttributeError, TypeError) as e:
                                logger.debug(
                                    "Session.update_state failed, assigning state directly: %s",
                                    e,
                                    exc_info=True,
                                )
                                session.state = result.new_state
                        await self._session_service.update_session(session)

                    command_results.append(CommandResultWrapper(result))
                    command_executed = True

                    # Update the content parts
                    new_parts = list(content)
                    if updated_text:
                        # Replace the text part with updated content
                        new_parts[last_text_part_index] = MessageContentPartText(
                            type="text", text=updated_text
                        )
                    else:
                        # Remove the text part if empty
                        new_parts.pop(last_text_part_index)
                    message.content = new_parts
            else:
                # Unknown command in part
                command_executed = True
                new_parts = list(content)
                if updated_text:
                    # Replace the text part with updated content
                    new_parts[last_text_part_index] = MessageContentPartText(
                        type="text", text=updated_text
                    )
                else:
                    # Remove the text part if empty
                    new_parts.pop(last_text_part_index)
                message.content = new_parts

        return ProcessedResult(
            modified_messages=modified_messages,
            command_executed=command_executed,
            command_results=command_results,
        )
