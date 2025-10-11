import logging
from typing import Any, TYPE_CHECKING

from src.core.commands.handler import ICommandHandler
from src.core.commands.handlers.failover_command_handler import (
    FailoverCommandHandler,
    SessionStateApplicationStateAdapter,
)
from src.core.commands.parser import CommandParser
from src.core.commands.registry import get_all_commands, get_command_handler
from src.core.domain import chat as models
from src.core.domain.chat import ChatMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.session_service_interface import ISessionService

if TYPE_CHECKING:
    from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class NewCommandService(ICommandService):
    """
    A service for processing and executing commands using the new architecture.
    """

    def __init__(
        self,
        session_service: ISessionService,
        command_parser: CommandParser,
        strict_command_detection: bool = False,
        app_state: IApplicationState | None = None,
    ):
        """
        Initializes the command service.

        Args:
            session_service: The session service.
            command_parser: The command parser.
            strict_command_detection: If True, only match commands on last non-blank line.
        """
        self.session_service = session_service
        self.command_parser = command_parser
        self.strict_command_detection = strict_command_detection
        self._app_state = app_state

    def _determine_command_prefix(self, session: "Session | None") -> str:
        """Resolve the effective command prefix for the provided session."""

        if session is not None:
            try:
                override = getattr(session.state, "command_prefix_override", None)
            except Exception:  # pragma: no cover - best-effort logging path
                override = None
            else:
                if isinstance(override, str) and override:
                    return override

        prefix: str | None = None
        if self._app_state is not None:
            try:
                prefix = self._app_state.get_command_prefix()
            except Exception as exc:  # pragma: no cover - defensive logging
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Unable to resolve command prefix from application state: %s",
                        exc,
                        exc_info=True,
                    )
                prefix = None

        if not isinstance(prefix, str) or not prefix:
            prefix = self.command_parser.command_prefix

        return prefix

    def _get_last_non_blank_line_content(self, text: str) -> str:
        """
        Extract only the last non-blank line from text.

        Args:
            text: The input text

        Returns:
            The last non-blank line, or empty string if none found
        """
        if not text:
            return ""

        lines = text.split("\n")
        # Find the last non-blank line
        for line in reversed(lines):
            if line.strip():  # Non-blank line
                return line
        return ""

    async def process_commands(
        self, messages: list[ChatMessage], session_id: str
    ) -> ProcessedResult:
        """
        Processes a list of messages to identify and execute commands.

        Args:
            messages: The list of messages to process.
            session_id: The ID of the session.

        Returns:
            A ProcessedResult object.
        """
        if not messages:
            return ProcessedResult(
                modified_messages=[], command_executed=False, command_results=[]
            )

        session = await self.session_service.get_session(session_id)
        if not session:
            logger.warning(f"Session '{session_id}' not found.")
            return ProcessedResult(
                modified_messages=messages, command_executed=False, command_results=[]
            )

        prefix_for_session = self._determine_command_prefix(session)

        modified_messages = messages.copy()
        command_results: list[Any] = []
        command_executed = False

        executed_command_name: str | None = None
        for message in reversed(modified_messages):
            if message.role != "user":
                continue

            content_str = ""
            if isinstance(message.content, str):
                content_str = message.content
            elif isinstance(message.content, list):
                # For now, we only look for commands in the first text part.
                content_str = next(
                    (
                        part.text
                        for part in message.content
                        if isinstance(part, models.MessageContentPartText)
                    ),
                    "",
                )

            # The command service should only ever parse the last line for commands.
            content_str = self._get_last_non_blank_line_content(content_str)

            parse_result = self.command_parser.parse(
                content_str, command_prefix=prefix_for_session
            )
            if not parse_result:
                continue

            command, matched_text = parse_result

            # Only execute commands that appear at the END of the message (after trimming)
            trimmed_content = content_str.rstrip()
            if not trimmed_content.endswith(matched_text):
                # Command is not at the end, skip it
                continue

            # Remove the command from the message content.
            if isinstance(message.content, str):
                # Find and remove the command from the full message content
                original_content = message.content
                idx = original_content.rfind(matched_text)
                if idx != -1:
                    before = original_content[:idx]
                    after = original_content[idx + len(matched_text) :]
                    if command.name == "hello":
                        # For 'hello': preserve structure without stripping
                        message.content = before + after
                    else:
                        # Default: strip trailing whitespace
                        message.content = (before + after).rstrip()
            elif isinstance(message.content, list):
                for i, part in enumerate(message.content):
                    if (
                        isinstance(part, models.MessageContentPartText)
                        and matched_text in part.text
                    ):
                        part.text = part.text.replace(matched_text, "").strip()
                        if not part.text:
                            message.content.pop(i)
                        break

            handler_class = get_command_handler(command.name)
            if not handler_class:
                logger.warning(f"Command '{command.name}' not found.")
                # Unknown command: if there are earlier messages, stop; otherwise continue
                if len(modified_messages) > 1:
                    command_executed = True
                    break
                continue

            handler: ICommandHandler
            if handler_class is FailoverCommandHandler:
                app_state_adapter = SessionStateApplicationStateAdapter(session)
                handler = handler_class(
                    self,
                    secure_state_access=app_state_adapter,
                    secure_state_modification=app_state_adapter,
                )
            else:
                handler = handler_class(self)

            result = await handler.handle(command, session)

            # Wrap the result with command name for proper response formatting
            class CommandResultWrapper:
                def __init__(self, command_name: str, result):
                    self.name = command_name
                    self.message = result.message
                    self.success = result.success
                    self.new_state = getattr(result, "new_state", None)
                    self._original_result = result

            executed_command_name = command.name
            wrapped_result = CommandResultWrapper(executed_command_name, result)
            command_executed = True
            (modified_messages.index(message) if message in modified_messages else 0)
            command_results.append(wrapped_result)
            break

        # If, after command execution, there is no meaningful user content left,
        # return a command-only result to avoid unnecessary backend calls.
        def _has_meaningful_user_content(msgs: list[ChatMessage]) -> bool:
            for m in msgs:
                if m.role != "user":
                    continue
                if isinstance(m.content, str) and m.content.strip():
                    return True
                if isinstance(m.content, list) and len(m.content) > 0:
                    return True
            return False

        # Only treat as command-only for specific commands (e.g., failover commands)
        command_only_names = {
            "create-failover-route",
            "delete-failover-route",
            "list-failover-routes",
            "route-append",
            "route-clear",
            "route-list",
            "route-prepend",
        }
        should_command_only = (
            executed_command_name in command_only_names
            if executed_command_name is not None
            else False
        )

        if should_command_only and not _has_meaningful_user_content(modified_messages):
            final_modified = []
        else:
            final_modified = modified_messages

        return ProcessedResult(
            modified_messages=final_modified,
            command_executed=command_executed,
            command_results=command_results,
        )

    async def get_command_handler(
        self, name: str
    ) -> (
        type[ICommandHandler] | None
    ):  # pragma: no cover - exercised via integration tests
        """Return the registered handler class for the provided command name."""
        return get_command_handler(name)

    async def get_all_commands(
        self,
    ) -> dict[
        str, ICommandHandler
    ]:  # pragma: no cover - exercised via integration tests
        """Return instantiated handlers for all registered commands."""
        handlers: dict[str, ICommandHandler] = {}
        for name, handler_class in sorted(get_all_commands().items()):
            handlers[name] = handler_class(self)
        return handlers
