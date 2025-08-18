import inspect
import logging
import re
from typing import Any

from fastapi import FastAPI

from src.command_config import CommandParserConfig, CommandProcessorConfig
from src.command_processor import CommandProcessor, get_command_pattern
from src.command_utils import (
    extract_feedback_from_tool_result,
    get_text_for_command_check,
    is_content_effectively_empty,
    is_original_purely_command,
    is_tool_call_result,
)
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.commands.set_command import SetCommand
from src.core.commands.unset_command import UnsetCommand
from src.core.domain.chat import ChatMessage, MessageContentPart
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.failover_commands import (
    CreateFailoverRouteCommand,
    DeleteFailoverRouteCommand,
    ListFailoverRoutesCommand,
    RouteAppendCommand,
    RouteClearCommand,
    RouteListCommand,
    RoutePrependCommand,
)
from src.core.domain.commands.hello_command import HelloCommand
from src.core.domain.commands.help_command import HelpCommand
from src.core.domain.commands.oneoff_command import OneoffCommand
from src.core.interfaces.domain_entities_interface import ISessionState

# Removed legacy import

# Removed legacy import

logger = logging.getLogger(__name__)


def create_command_instances(
    app: FastAPI, functional_backends: set[str] | None = None
) -> list[BaseCommand]:
    """
    Create instances of all available commands.
    This is a temporary replacement for the old command creation logic.
    """
    # The app and functional_backends arguments are ignored for now as the new
    # command classes do not require them at construction time.
    commands = [
        HelloCommand(),
        HelpCommand(),
        OneoffCommand(),
        SetCommand(),
        UnsetCommand(),
        CreateFailoverRouteCommand(),
        DeleteFailoverRouteCommand(),
        ListFailoverRoutesCommand(),
        RouteAppendCommand(),
        RoutePrependCommand(),
        RouteListCommand(),
        RouteClearCommand(),
    ]
    return commands


class CommandParser:
    """Parse and apply proxy commands embedded in chat messages."""

    def __init__(
        self,
        config: "CommandParserConfig",
        command_prefix: str,
    ) -> None:
        self.config = config
        self.command_pattern = get_command_pattern(command_prefix)
        self.handlers: dict[str, BaseCommand] = {}
        self.command_results: list[CommandResult] = []

        for cmd_instance in create_command_instances(
            config.app, config.functional_backends
        ):
            self.register_command(cmd_instance)

        processor_config = CommandProcessorConfig(
            proxy_state=config.proxy_state,
            app=config.app,
            command_pattern=self.command_pattern,
            handlers=self.handlers,
            preserve_unknown=config.preserve_unknown,
            command_results=self.command_results,
        )
        self.command_processor = CommandProcessor(processor_config)

    def register_command(self, command: BaseCommand) -> None:
        self.handlers[command.name.lower()] = command

    def _is_content_effectively_empty(self, content: Any) -> bool:
        """Checks if message content is effectively empty after processing."""
        return is_content_effectively_empty(content)

    def _is_original_purely_command(self, original_content: Any) -> bool:
        """Checks if the original message content was purely a command, ignoring comments."""
        return is_original_purely_command(original_content, self.command_pattern)

    def _is_tool_call_result(self, text: str) -> bool:
        """Check if the text appears to be a tool call result rather than direct user input."""
        return is_tool_call_result(text)

    def _extract_feedback_from_tool_result(self, text: str) -> str:
        """Extract user feedback from tool call results that contain feedback sections."""
        return extract_feedback_from_tool_result(text)

    def _get_text_for_command_check(self, content: Any) -> str:
        """Extracts and prepares text from message content for command checking."""
        return get_text_for_command_check(content)

    async def _execute_commands_in_target_message(
        self, target_idx: int, modified_messages: list[ChatMessage]
    ) -> bool:
        """Processes commands in the specified message and updates it.
        Returns True if a command was found and an attempt to execute it was made.
        """
        msg_to_process = modified_messages[target_idx]
        original_content = msg_to_process.content
        processed_content, found, modified = await self._process_content(msg_to_process)
        if not found:
            return False

        # Handle async command results
        if self.command_results:
            new_results: list = []
            for cr in self.command_results:
                if inspect.isawaitable(cr):
                    # Create a new event loop to run the awaitable
                    import asyncio

                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(cr)
                        new_results.append(result)
                    finally:
                        loop.close()
                else:
                    new_results.append(cr)
            self.command_results = new_results

        processed_content, modified = await self._maybe_use_error_message(
            original_content, processed_content, modified
        )
        self._apply_processed_content(
            msg_to_process, target_idx, original_content, processed_content, modified
        )
        return True

    async def _process_content(
        self, msg_to_process: ChatMessage
    ) -> tuple[str | list[MessageContentPart] | None, bool, bool]:
        if isinstance(msg_to_process.content, str):
            return await self.command_processor.handle_string_content(
                msg_to_process.content
            )
        if isinstance(msg_to_process.content, list):
            return await self.command_processor.handle_list_content(
                msg_to_process.content
            )
        return None, False, False

    async def _maybe_use_error_message(
        self,
        original_content: Any,
        processed_content: str | list[MessageContentPart] | None,
        modified: bool,
    ) -> tuple[str | list[MessageContentPart] | None, bool]:
        if (
            self._is_original_purely_command(original_content)
            and self._is_content_effectively_empty(processed_content)
            and self.command_results
        ):
            last_result = self.command_results[-1]
            # Handle async command result
            if inspect.isawaitable(last_result):
                last_result = await last_result
            if not last_result.success and last_result.message:
                return last_result.message, True
        return processed_content, modified

    def _apply_processed_content(
        self,
        msg_to_process: ChatMessage,
        target_idx: int,
        original_content: Any,
        processed_content: str | list[MessageContentPart] | None,
        modified: bool,
    ) -> None:
        if modified and processed_content is not None:
            msg_to_process.content = processed_content
            logger.info(
                "Content modified by command in message index %s. Role: %s.",
                target_idx,
                msg_to_process.role,
            )
        elif (
            modified
            and processed_content is None
            and isinstance(original_content, list)
        ):
            # Entire list content was consumed by the.
            msg_to_process.content = []
            logger.info(
                "List content removed by command in message index %s. Role: %s.",
                target_idx,
                msg_to_process.role,
            )

    def _filter_empty_messages(
        self,
        processed_messages: list[ChatMessage],
        original_messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """Filters out messages that became empty, unless they were purely commands."""
        final_messages: list[ChatMessage] = []
        for original_msg_idx, current_msg_state in enumerate(processed_messages):
            is_empty = is_content_effectively_empty(current_msg_state.content)

            if is_empty:
                original_content = original_messages[original_msg_idx].content
                if is_original_purely_command(original_content, self.command_pattern):
                    # Pure command became empty. Retain it, ensuring content is canonical empty.
                    current_msg_state.content = (
                        [] if isinstance(original_content, list) else ""
                    )
                    logger.info(
                        "Retaining message (role: %s, index: %s) as transformed empty content "
                        "because it was originally a pure command.",
                        current_msg_state.role,
                        original_msg_idx,
                    )
                else:
                    logger.info(
                        "Removing message (role: %s, index: %s) as its content "
                        "became effectively empty after command processing and was not a pure command.",
                        current_msg_state.role,
                        original_msg_idx,
                    )
                    continue
            final_messages.append(current_msg_state)
        return final_messages

    async def process_messages(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], bool]:
        self.command_results.clear()
        if not messages:
            logger.debug("process_messages received empty messages list.")
            return messages, False

        # Find the index of the last message containing a command to avoid unnecessary processing.
        command_message_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            text_for_check = get_text_for_command_check(messages[i].content)
            if self.command_pattern.search(text_for_check):
                command_message_idx = i
                break

        # If no command is found, return the original list reference, avoiding any copies.
        if command_message_idx == -1:
            return messages, False

        # A command was found. Create a shallow copy of the list and deep copy only the message
        # that needs to be modified. This is the core performance optimization.
        modified_messages = list(messages)
        msg_to_process = modified_messages[command_message_idx].model_copy(deep=True)
        modified_messages[command_message_idx] = msg_to_process

        overall_commands_processed = await self._execute_commands_in_target_message(
            command_message_idx, modified_messages
        )

        # The original filtering logic is now safe to use because we have both the
        # modified list and the original list for comparison.
        final_messages = self._filter_empty_messages(modified_messages, messages)

        if not final_messages and overall_commands_processed:
            logger.info(
                "All messages were removed after command processing. "
                "This might indicate a command-only request."
            )

        logger.debug(
            "Finished processing messages. Final message count: %s. "
            "Commands processed overall: %s",
            len(final_messages),
            overall_commands_processed,
        )
        return final_messages, overall_commands_processed


async def _process_text_for_commands(
    text_content: str,
    current_proxy_state: ISessionState,
    command_pattern: re.Pattern,
    app: FastAPI,
    functional_backends: set[str] | None = None,
) -> tuple[str, bool]:
    # This function is primarily for testing and specific internal uses where a
    # CommandParser instance is not fully initialized with all handlers.
    # It creates a minimal parser to process a single text string.
    parser_config = CommandParserConfig(
        proxy_state=current_proxy_state,
        app=app,
        preserve_unknown=True,
        functional_backends=functional_backends,
    )
    parser = CommandParser(parser_config, command_prefix="")
    # Override the command_pattern as it's passed directly for this helper
    parser.command_pattern = command_pattern
    # Use the internal command_processor for actual text processing
    processed_text, commands_found, _ = (
        await parser.command_processor.handle_string_content(text_content)
    )

    # For tests relying on this helper, if a command-only message was processed
    # and failed, return the error message from the command execution.
    if commands_found and not processed_text.strip() and parser.command_results:
        last_result = parser.command_results[-1]
        if not last_result.success and last_result.message:
            return last_result.message, True

    return processed_text, commands_found


async def process_commands_in_messages(
    messages: list[ChatMessage],
    current_proxy_state: ISessionState,
    app: FastAPI | None = None,
    command_prefix: str = DEFAULT_COMMAND_PREFIX,
) -> tuple[list[ChatMessage], bool]:
    """
    Processes a list of chat messages to identify and execute embedded commands.

    This is the primary public interface for command processing. It initializes
    a CommandParser and uses it to process the messages.
    """
    if not messages:
        logger.debug("process_commands_in_messages received empty messages list.")
        return messages, False

    functional_backends: set[str] | None = None
    if app and hasattr(app, "state") and hasattr(app.state, "functional_backends"):
        functional_backends = app.state.functional_backends
    else:
        logger.warning(
            "FastAPI app instance or functional_backends not available in "
            "app.state. CommandParser will be initialized without specific "
            "functional_backends.",
        )

    parser_config = CommandParserConfig(
        proxy_state=current_proxy_state,
        app=app,  # type: ignore
        preserve_unknown=True,
        functional_backends=functional_backends,
    )
    parser = CommandParser(parser_config, command_prefix=command_prefix)

    final_messages, commands_processed = await parser.process_messages(messages)

    return final_messages, commands_processed
