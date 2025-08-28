"""Fixed command service with correct indentation."""

import asyncio
import logging
import re
from typing import Any

from src.core.domain.chat import ChatMessage
from src.core.domain.command_context import CommandContext
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_argument_parser_interface import (
    ICommandArgumentParser,
)
from src.core.interfaces.command_sanitizer_interface import ICommandSanitizer
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
    # Pattern to match commands with optional arguments in parentheses, using named groups
    # to match the legacy semantics used in some tests.
    # Allow command names with letters, digits, underscore, and hyphen
    return re.compile(rf"{escaped_prefix}(?P<cmd>[\w-]+)(?:\((?P<args>[^)]*)\))?")


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
        argument_parser: ICommandArgumentParser | None = None,
        command_sanitizer: ICommandSanitizer | None = None,
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
        self._argument_parser = argument_parser
        self._command_sanitizer = command_sanitizer

    async def register_command(self, command_name: str, command_handler: Any) -> None:
        """Register a command handler.

        Args:
            command_name: The name of the command
            command_handler: The command handler to register
        """
        self._registry.register(command_handler)

    def get_command_handlers(self) -> dict[str, BaseCommand]:
        """Get all registered command handlers.

        Returns:
            A dictionary of command name to handler
        """
        return self._registry.get_all()

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

        executed_last_message = False
        for i in range(len(modified_messages) - 1, -1, -1):
            message = modified_messages[i]

            if message.role != "user":
                continue

            content = message.content or ""
            # Case 1: String content
            if isinstance(content, str):
                logger.debug(f"Checking message content for commands: '{content}'")

                parsed_command = self._parse_command_from_message(content)

                if parsed_command:
                    match_start = parsed_command.get("match_start", 0)
                    match_end = parsed_command.get("match_end", len(content))
                    if not executed_last_message:
                        # Execute only for the last command-bearing message
                        execution_result = await self._execute_parsed_command(
                            parsed_command, session, modified_messages
                        )
                        if execution_result:
                            # Known command (string content): prefer suffix; if command at end, keep prefix
                            before = content[:match_start]
                            after = content[match_end:]
                            if after.strip():
                                message.content = f" {after.lstrip()}"
                            else:
                                message.content = before.rstrip()
                            logger.debug(
                                f"Updated message content: '{message.content}'"
                            )
                            command_executed = True
                            command_results.append(execution_result["wrapped_result"])
                            executed_last_message = True
                        elif parsed_command["cmd_name"]:
                            # Unknown: preserve both sides with double space when in middle
                            before = content[:match_start]
                            after = content[match_end:]
                            message.content = (
                                f"{before.rstrip()}  {after.lstrip()}"
                                if before and after
                                else before + after
                            )
                            command_executed = True
                            executed_last_message = True
                    else:
                        # Earlier messages: strip command text without executing
                        before = content[:match_start]
                        after = content[match_end:]
                        if before and after:
                            message.content = f"{before.rstrip()} {after.lstrip()}"
                        elif before:
                            message.content = f"{before.rstrip()} "
                        else:
                            # Command is the entire content - preserve it for earlier messages
                            pass  # Leave the message content unchanged
                elif not self._preserve_unknown and "!/" in content:
                    # Unknown command pattern: preserve exact double-space when command removed in middle
                    # Replace first occurrence of pattern with a single space and then normalize to ensure
                    # two spaces between words if removal happens between tokens.
                    import re

                    message.content = re.sub(r"\s*!/\S+\s*", "  ", content, count=1)
                    command_executed = True
                # Continue to earlier messages to apply stripping logic where needed

            # Case 2: List of content parts (e.g., MessageContentPartText)
            if isinstance(content, list):
                new_parts = []
                processed_part_index = None
                for idx, part in enumerate(content):
                    text = getattr(part, "text", None)
                    if not isinstance(text, str):
                        new_parts.append(part)
                        continue
                    parsed_command = self._parse_command_from_message(text)
                    if parsed_command and processed_part_index is None:
                        # Replace the part's text with combined (prefix + suffix) and stop after first
                        part.text = parsed_command["updated_combined"]
                        execution_result = await self._execute_parsed_command(
                            parsed_command, session, modified_messages
                        )
                        if execution_result or parsed_command["cmd_name"]:
                            command_executed = True
                            if execution_result:
                                command_results.append(
                                    execution_result["wrapped_result"]
                                )
                        # Keep the modified part only if non-empty; drop empty command part per tests
                        if part.text and part.text.strip():
                            new_parts.append(part)
                        processed_part_index = idx
                        # Do not process subsequent parts for commands in this message
                        # but keep them as-is
                        continue
                    else:
                        # Keep non-command parts until a command is found
                        new_parts.append(part)
                message.content = new_parts
                break

        return ProcessedResult(
            modified_messages=modified_messages,
            command_executed=command_executed,
            command_results=command_results,
        )

    def _parse_command_from_message(self, content: str) -> dict[str, Any] | None:
        """Parse command from message content and return command details.

        Uses the shared get_command_pattern with default prefix to ensure
        consistent detection semantics across the codebase.
        """
        pattern = get_command_pattern("!/")
        m = pattern.search(content)
        if not m:
            return None

        cmd_name = (m.group("cmd") or "").strip()
        args_str = (m.group("args") or "").strip() or None
        match_start, match_end = m.start(), m.end()

        # Extract remaining content after the command and rebuild updated content
        before = content[:match_start]
        after = content[match_end:]
        # For parts: updated_combined should keep only suffix for that part's text
        # Normalize leading whitespace in the after part to a single space when starts with newline/tab
        if after and after[0] in ["\n", "\t"]:
            updated_combined = " " + after[1:]
        else:
            updated_combined = after

        updated_content = before + after

        logger.debug(
            "Parsed command: name=%s, args=%r, updated_content=%r",
            cmd_name,
            args_str,
            updated_content,
        )

        return {
            "cmd_name": cmd_name,
            "args_str": args_str,
            "remaining": after,
            "updated_content": updated_content,
            "updated_combined": updated_combined,
            "command_handler": self._registry.get(cmd_name),
            "match_start": match_start,
            "match_end": match_end,
        }

    def _parse_command_arguments(self, args_str: str | None) -> dict[str, Any]:
        """Parse command arguments from argument string using injected parser.

        Falls back to legacy function to maintain compatibility until DI wiring
        is complete across the app.
        """
        if self._argument_parser is not None:
            return self._argument_parser.parse(args_str)
        from src.core.common.command_args import parse_command_arguments

        return parse_command_arguments(args_str)

    async def _execute_parsed_command(
        self,
        parsed_command: dict[str, Any],
        session: Any,
        modified_messages: list[ChatMessage],
    ) -> dict[str, Any] | None:
        """Execute a parsed command and return execution result."""
        cmd_name = parsed_command["cmd_name"]
        cmd = parsed_command["command_handler"]

        logger.debug(f"Attempting to retrieve command: '{cmd_name}'")
        logger.debug(
            f"CommandRegistry contents: {list(self._registry.get_all().keys())}"
        )
        if not cmd:
            logger.warning(f"Command '{cmd_name}' not found in registry.")
            return None

        if session is None:
            logger.warning(f"Cannot execute command {cmd_name} without a session")
            return None

        # Parse arguments
        args = self._parse_command_arguments(parsed_command["args_str"])

        logger.info(
            f"Executing command: {cmd_name} with session: {session.session_id if session else 'N/A'}"
        )

        # Create command context with minimal attributes used by commands
        backend_types = {
            "openai",
            "anthropic",
            "openrouter",
            "gemini",
            "qwen-oauth",
            "zai",
        }
        backend_factory_stub = type(
            "BackendFactoryStub", (), {"_backend_types": backend_types}
        )()

        context = CommandContext(
            command_registry=self._registry,
            backend_factory=backend_factory_stub,
            backend_type=None,
        )

        # Execute command
        result: CommandResult
        try:
            coro_result = cmd.execute(args, session, context)
            if asyncio.iscoroutine(coro_result):
                result = await coro_result
            else:
                result = coro_result
        except TypeError:
            result = coro_result

        # Update session state if needed
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
                except (AttributeError, TypeError):
                    session.state = result.new_state
            else:
                logger.info(
                    "No new_state in command result, not updating session state"
                )
            await self._session_service.update_session(session)
            logger.info("Session updated in repository")

        wrapped_result = CommandResultWrapper(result)
        return {"wrapped_result": wrapped_result}
