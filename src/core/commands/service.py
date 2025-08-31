import logging
from typing import Any

from src.core.commands.handler import ICommandHandler
from src.core.commands.parser import CommandParser
from src.core.commands.registry import get_command_handler
from src.core.domain import chat as models
from src.core.domain.chat import ChatMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


class NewCommandService(ICommandService):
    """
    A service for processing and executing commands using the new architecture.
    """

    def __init__(
        self,
        session_service: ISessionService,
        command_parser: CommandParser,
    ):
        """
        Initializes the command service.

        Args:
            session_service: The session service.
            command_parser: The command parser.
        """
        self.session_service = session_service
        self.command_parser = command_parser

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

        modified_messages = messages.copy()
        command_results: list[Any] = []
        command_executed = False

        executed_at: int | None = None
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

            parse_result = self.command_parser.parse(content_str)
            if not parse_result:
                continue

            command, matched_text = parse_result

            # Remove the command from the message content.
            if isinstance(message.content, str):
                if command.name == "hello":
                    # For 'hello': replace command with empty space to preserve structure
                    idx = content_str.find(matched_text)
                    if idx != -1:
                        before = content_str[:idx]
                        after = content_str[idx + len(matched_text) :]
                        message.content = before + after
                    else:
                        message.content = content_str
                else:
                    # Default: replace the matched command in place and trim
                    message.content = content_str.replace(matched_text, "").strip()
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
                # Bridge to legacy CommandRegistry for integration tests that register
                # BaseCommand handlers (e.g., failover route commands)
                try:
                    from src.core.services.command_service import (
                        CommandRegistry as LegacyRegistry,
                    )

                    legacy = LegacyRegistry.get_instance()
                except Exception:
                    legacy = None

                if legacy is not None:
                    legacy_handler = legacy.get(command.name)
                    if legacy_handler is not None:
                        # Execute legacy command and wrap result
                        legacy_result = await legacy_handler.execute(
                            command.args or {}, session
                        )

                        class CommandResultWrapperLegacy:
                            def __init__(self, name: str, result):
                                self.name = name
                                self.message = result.message
                                self.success = result.success
                                self.new_state = getattr(result, "new_state", None)
                                self._original_result = result

                        command_results.append(
                            CommandResultWrapperLegacy(command.name, legacy_result)
                        )
                        # Indicate command-only path by clearing modified messages
                        modified_messages = []
                        command_executed = True
                        executed_at = (
                            modified_messages.index(message)
                            if message in modified_messages
                            else 0
                        )
                        break

                logger.warning(f"Command '{command.name}' not found.")
                # Unknown command with no legacy fallback: if there are earlier messages, stop; otherwise continue
                if len(modified_messages) > 1:
                    command_executed = True
                    break
                continue

            handler: ICommandHandler = handler_class()
            result = await handler.handle(command, session)

            # Wrap the result with command name for proper response formatting
            class CommandResultWrapper:
                def __init__(self, command_name: str, result):
                    self.name = command_name
                    self.message = result.message
                    self.success = result.success
                    self.new_state = getattr(result, "new_state", None)
                    self._original_result = result

            wrapped_result = CommandResultWrapper(command.name, result)
            command_executed = True
            executed_at = (
                modified_messages.index(message) if message in modified_messages else 0
            )
            command_results.append(wrapped_result)
            break

        # Cleanup: strip commands from earlier messages without executing them
        if command_executed and executed_at is not None:
            for idx in range(executed_at):
                m = modified_messages[idx]
                if m.role != "user":
                    continue
                content_val = m.content if isinstance(m.content, str) else None
                if not isinstance(content_val, str):
                    continue
                pr = self.command_parser.parse(content_val)
                if pr:
                    _, match = pr
                    m.content = content_val.replace(match, "").strip()
                else:
                    m.content = content_val.strip()

        return ProcessedResult(
            modified_messages=modified_messages,
            command_executed=command_executed,
            command_results=command_results,
        )
