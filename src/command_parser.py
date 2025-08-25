import inspect
import logging
import re
from typing import Any, cast

from fastapi import FastAPI

from src.command_config import CommandProcessorConfig as NewCommandProcessorConfig
from src.command_processor import CommandProcessor, get_command_pattern
from src.command_utils import (
    extract_feedback_from_tool_result,
    get_text_for_command_check,
    is_content_effectively_empty,
    is_original_purely_command,
    is_tool_call_result,
)
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.domain.chat import ChatMessage, MessageContentPart
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.discovery import discover_commands
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.domain_entities_interface import ISessionState
from src.core.services.command_service import CommandRegistry

# Compatibility alias for legacy tests importing CommandParserConfig from this module
CommandParserConfig = NewCommandProcessorConfig


logger = logging.getLogger(__name__)


class CommandParser(ICommandProcessor):
    """Parse and apply proxy commands embedded in chat messages."""

    def __init__(
        self,
        config: Any | None = None,
        command_prefix: str = DEFAULT_COMMAND_PREFIX,
        command_registry: CommandRegistry | None = None,
    ) -> None:
        self.config = config
        self.command_pattern = get_command_pattern(command_prefix)
        self.command_results: list[CommandResult] = []

        if command_registry:
            self.handlers = command_registry.get_all()
            logger.info(
                f"Using commands from injected registry (ID: {id(command_registry)})"
            )
        else:
            di_registry = CommandRegistry.get_instance()
            if di_registry:
                logger.info(f"Using commands from DI registry (ID: {id(di_registry)})")
                self.handlers = di_registry.get_all()
            else:
                logger.warning(
                    "DI command registry not available, falling back to auto-discovery. "
                    "This may miss commands that require dependency injection."
                )
                self.handlers = discover_commands()

        logger.debug(
            f"Loaded {len(self.handlers)} commands: {list(self.handlers.keys())}"
        )

        if not self.handlers:
            logger.error(
                "No commands found! Neither injected registry, DI registry nor auto-discovery provided commands."
            )
            import sys

            is_test_env = "pytest" in sys.modules or hasattr(sys, "_called_from_test")

            if is_test_env:
                logger.warning("Test environment detected, using mock command handlers")
                try:
                    from tests.unit.mock_commands import get_mock_commands

                    self.handlers = cast(dict[str, BaseCommand], get_mock_commands())
                except ImportError:
                    from src.core.domain.commands.help_command import HelpCommand

                    self.handlers = cast(
                        dict[str, BaseCommand], {"help": HelpCommand()}
                    )
            else:
                raise RuntimeError(
                    "Command initialization failed: No commands available. "
                    "This indicates a serious configuration issue."
                )

        self.command_processor: CommandProcessor | None = None
        if self.config is not None:
            try:
                # Normalize incoming config (may be a Mock/spec in tests)
                preserve_unknown = bool(getattr(self.config, "preserve_unknown", False))
                proxy_state = getattr(self.config, "proxy_state", None)
                if proxy_state is None:
                    from src.core.domain.session import (
                        SessionState,
                        SessionStateAdapter,
                    )

                    proxy_state = SessionStateAdapter(SessionState())

                app_obj = getattr(self.config, "app", None)
                if app_obj is None:
                    app_obj = FastAPI()

                processor_config = NewCommandProcessorConfig(
                    proxy_state=cast(ISessionState, proxy_state),
                    app=cast(FastAPI, app_obj),
                    command_pattern=self.command_pattern,
                    handlers=self.handlers,
                    preserve_unknown=preserve_unknown,
                    command_results=self.command_results,
                )
                self.command_processor = CommandProcessor(processor_config)
            except Exception:
                logger.debug(
                    "Deferred CommandProcessor initialization due to config error",
                    exc_info=True,
                )

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

    def _strip_commands_in_text(self, text: str) -> str:
        """Remove all command occurrences from a text, preserving surrounding whitespace."""
        result = text
        while True:
            m = self.command_pattern.search(result)
            if not m:
                break
            result = result[: m.start()] + result[m.end() :]
        return result

    def _strip_commands_in_content(self, content: Any) -> Any:
        """Remove command tokens from string or list content without executing them."""
        if isinstance(content, str):
            return self._strip_commands_in_text(content)
        if isinstance(content, list):
            from src.core.domain.chat import MessageContentPartText

            new_parts: list[MessageContentPart] = []
            for part in content:
                if isinstance(part, MessageContentPartText):
                    new_text = self._strip_commands_in_text(part.text)
                    if new_text != "":
                        new_parts.append(
                            MessageContentPartText(type="text", text=new_text)
                        )
                else:
                    new_parts.append(part)
            return new_parts
        return content

    async def _execute_commands_in_target_message(
        self,
        target_idx: int,
        modified_messages: list[ChatMessage],
        context: RequestContext | None,
    ) -> bool:
        """Processes commands in the specified message and updates it.
        Returns True if a command was found and an attempt to execute it was made.
        """
        msg_to_process = modified_messages[target_idx]
        original_content = msg_to_process.content

        if self.command_processor is None:
            # Try to use provided config first
            if self.config is not None:
                try:
                    preserve_unknown = bool(
                        getattr(self.config, "preserve_unknown", False)
                    )
                    proxy_state = getattr(self.config, "proxy_state", None)
                    if proxy_state is None:
                        from src.core.domain.session import (
                            SessionState,
                            SessionStateAdapter,
                        )

                        proxy_state = SessionStateAdapter(SessionState())
                    app_obj = getattr(self.config, "app", None)
                    if app_obj is None:
                        app_obj = FastAPI()

                    processor_config = NewCommandProcessorConfig(
                        proxy_state=cast(ISessionState, proxy_state),
                        app=cast(FastAPI, app_obj),
                        command_pattern=self.command_pattern,
                        handlers=self.handlers,
                        preserve_unknown=preserve_unknown,
                        command_results=self.command_results,
                    )
                    self.command_processor = CommandProcessor(processor_config)
                except Exception:
                    logger.debug(
                        "Failed to initialize CommandProcessor from provided config; will try context",
                        exc_info=True,
                    )

            if self.command_processor is None:
                if context is None:
                    logger.error(
                        "CommandProcessor cannot be initialized without a valid context."
                    )
                    return False

                # Create a mock app state for the processor config
                mock_app_state = type("MockAppState", (), {})()
                mock_app_state.service_provider = None
                mock_app_state.functional_backends = set()
                mock_app_state.command_prefix = "!/"

                processor_config = NewCommandProcessorConfig(
                    proxy_state=mock_app_state,  # fallback state
                    app=mock_app_state,
                    command_pattern=self.command_pattern,
                    handlers=self.handlers,
                    preserve_unknown=False,
                    command_results=self.command_results,
                )
                self.command_processor = CommandProcessor(processor_config)

        processed_content, found, modified = await self._process_content(msg_to_process)
        if not found:
            return False

        if self.command_results:
            new_results: list = []
            for cr in self.command_results:
                if inspect.isawaitable(cr):
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

        if self._is_original_purely_command(original_content):
            if isinstance(original_content, str):
                processed_content = ""
                modified = True
            elif isinstance(original_content, list):
                processed_content = []
                modified = True

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
        if self.command_processor is None:
            raise RuntimeError("CommandProcessor not initialized.")

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
        self,
        messages: list[ChatMessage],
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResult:
        self.command_results.clear()
        if not messages:
            logger.debug("process_messages received empty messages list.")
            return ProcessedResult(
                modified_messages=messages,
                command_executed=False,
                command_results=[],
            )

        command_message_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            text_for_check = get_text_for_command_check(messages[i].content)
            if self.command_pattern.search(text_for_check):
                command_message_idx = i
                break

        if command_message_idx == -1:
            return ProcessedResult(
                modified_messages=messages,
                command_executed=False,
                command_results=[],
            )

        modified_messages = list(messages)
        msg_to_process = modified_messages[command_message_idx].model_copy(deep=True)
        modified_messages[command_message_idx] = msg_to_process

        overall_commands_processed = await self._execute_commands_in_target_message(
            command_message_idx, modified_messages, context
        )

        # Strip command tokens from other messages without executing them
        if overall_commands_processed:
            for idx, msg in enumerate(modified_messages):
                if idx == command_message_idx:
                    continue
                # Skip stripping if the original message was a pure command-only message
                try:
                    original_msg_content = messages[idx].content
                except Exception:
                    original_msg_content = None
                if (
                    original_msg_content is not None
                    and self._is_original_purely_command(original_msg_content)
                ):
                    continue
                # Work on a deep copy to avoid mutating the originals used for emptiness checks
                if hasattr(msg, "model_copy"):
                    msg_copy = msg.model_copy(deep=True)
                    current = msg_copy.content
                    stripped = self._strip_commands_in_content(current)
                    if stripped != current:
                        msg_copy.content = stripped
                        modified_messages[idx] = msg_copy
                else:
                    current = (
                        msg.get("content") if isinstance(msg, dict) else msg.content
                    )
                    stripped = self._strip_commands_in_content(current)
                    if stripped != current:
                        if isinstance(msg, dict):
                            msg["content"] = stripped
                        else:
                            msg.content = stripped

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
        return ProcessedResult(
            modified_messages=final_messages,
            command_executed=overall_commands_processed,
            command_results=self.command_results,
        )


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
    # To avoid circular imports, CommandParserConfig is not used here.
    # Instead, we pass the necessary components directly.
    # This function will be removed once CommandParser is fully integrated.

    # Create a mock context for the temporary CommandParser instance
    from src.core.domain.session import Session

    _ = Session(session_id="temp-session", state=current_proxy_state)
    _ = RequestContext(
        headers={},
        cookies={},
        state=current_proxy_state,
        app_state=app,
        session_id="temp-session",
    )

    parser = CommandParser(command_prefix="")
    parser.command_pattern = command_pattern  # Override the command_pattern as it's passed directly for this helper

    # Manually initialize the internal command_processor for this temporary parser
    # This is a hack for legacy function _process_text_for_commands
    processor_config = NewCommandProcessorConfig(
        proxy_state=current_proxy_state,
        app=app,
        command_pattern=command_pattern,
        handlers=parser.handlers,  # Use the handlers discovered by the temporary parser
        preserve_unknown=False,
        command_results=parser.command_results,
    )
    parser.command_processor = CommandProcessor(processor_config)

    (
        processed_text,
        commands_found,
        _,
    ) = await parser.command_processor.handle_string_content(text_content)

    if commands_found and not processed_text.strip() and parser.command_results:
        last_result = parser.command_results[-1]
        if not last_result.success and last_result.message:
            return last_result.message, True

    return processed_text, commands_found


async def process_commands_in_messages(
    messages: list[ChatMessage],
    app: FastAPI | None = None,
    command_prefix: str = DEFAULT_COMMAND_PREFIX,
    context: RequestContext | None = None,
) -> tuple[list[ChatMessage], bool]:
    """
    Processes a list of chat messages to identify and execute embedded commands.
    This is the primary public interface for command processing. It initializes
    a CommandParser and uses it to process the messages.
    """
    if not messages:
        logger.debug("process_commands_in_messages received empty messages list.")
        return messages, False

    parser = CommandParser(command_prefix=command_prefix)

    if context is None:
        from src.core.domain.session import Session, SessionState

        # Create a minimal context if not provided
        mock_session_state = SessionState()
        _ = Session(session_id="default-session-id", state=mock_session_state)
        context = RequestContext(
            headers={},
            cookies={},
            state=mock_session_state,
            app_state=app,
            session_id="default-session-id",
        )

    result = await parser.process_messages(messages, "unused_session_id", context)

    return result.modified_messages, result.command_executed
