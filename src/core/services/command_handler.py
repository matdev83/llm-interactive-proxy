"""
Command handler implementation.

This module provides command processing and command-only flow detection,
extracted from RequestProcessor during refactoring.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from src.core.domain.chat import ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.request_processor_internal import ICommandHandler

if TYPE_CHECKING:
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.command_processor_interface import ICommandProcessor
    from src.core.interfaces.response_manager_interface import IResponseManager
    from src.core.interfaces.session_manager_interface import ISessionManager
    from src.core.services.artifact_service import ArtifactService

logger = logging.getLogger(__name__)


class CommandHandler(ICommandHandler):
    """
    Handles command processing and command-only flow decisions.

    This component extracts command processing logic from RequestProcessor,
    including:
    - Global command disable behavior
    - Command processing delegation
    - Command-only early returns
    - Special agent-specific command handling (e.g., Cline agent fast-path)
    - Artifact normalization after command execution
    """

    def __init__(
        self,
        command_processor: ICommandProcessor,
        session_manager: ISessionManager,
        response_manager: IResponseManager,
        app_state: IApplicationState | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        """
        Initialize the command handler.

        Args:
            command_processor: Service for processing commands in messages
            session_manager: Service for managing session state
            response_manager: Service for creating response envelopes
            app_state: Optional application state for configuration access
            artifact_service: Optional service for artifact preview normalization
        """
        self._command_processor = command_processor
        self._session_manager = session_manager
        self._response_manager = response_manager
        self._app_state = app_state
        self._artifact_service = artifact_service

    async def handle(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ProcessedResult | ResponseEnvelope | StreamingResponseEnvelope:
        """
        Process commands and determine if command-only flow should be taken.

        Returns:
            - ProcessedResult for backend flow (commands were executed but backend call needed)
            - ResponseEnvelope or StreamingResponseEnvelope for command-only flow
              (commands were executed and no backend call needed)

        This method handles:
        - Command processing delegation
        - Artifact preview normalization after command execution
        - Command-only flow detection
        - Special agent-specific command handling (e.g., Cline agent fast-path)
        - Session recording for command-only flows
        """
        # Process commands in the request
        command_result = await self._handle_command_processing(
            request, session_id, context
        )

        # Debug logging
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Command processing result: executed={command_result.command_executed}, "
                f"modified_messages_count={len(command_result.modified_messages or [])}"
            )
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Command processing result: command_executed={command_result.command_executed}, "
                f"modified_messages={len(command_result.modified_messages) if hasattr(command_result.modified_messages, '__len__') else 0}, "
                f"command_results={len(command_result.command_results) if hasattr(command_result.command_results, '__len__') else 0}"
            )

        # Normalize artifact previews after command execution
        if self._artifact_service is not None:
            self._artifact_service.normalize_artifact_previews(command_result)

        # Special handling: Cline agent expects tool_calls for proxy commands
        try:
            if (
                getattr(session, "agent", None) == "cline"
                and command_result.command_executed
            ):
                await self._session_manager.record_command_in_session(
                    request, session_id
                )
                return await self._response_manager.process_command_result(
                    command_result, cast(Session, session)
                )
        except (AttributeError, TypeError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Cline agent fast-path failed; continuing", exc_info=True)
            # Fallback to normal processing if attributes are missing

        # Check if we should take the command-only path
        if self._should_process_command_only(command_result):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Taking command result path for session {session_id}")
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Command executed with no modified messages - returning command result without backend call"
                )
            await self._session_manager.record_command_in_session(request, session_id)
            return await self._response_manager.process_command_result(
                command_result, cast(Session, session)
            )

        # Backend flow: return ProcessedResult for further processing
        return command_result

    async def _handle_command_processing(
        self, request_data: ChatRequest, session_id: str, context: RequestContext
    ) -> ProcessedResult:
        """Handle command processing with global disable check and fallback."""
        # Respect global disable for interactive commands via injected application state
        should_disable_commands = False
        if self._app_state is not None:
            try:
                # Check both disable_commands and disable_interactive_commands
                should_disable_commands = bool(
                    self._app_state.get_disable_commands()
                    or self._app_state.get_disable_interactive_commands()
                )
            except AttributeError as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Error getting disable_commands state: {e}", exc_info=True
                    )
                should_disable_commands = False

        if should_disable_commands:
            # When commands are disabled, filter commands from messages for security
            # This prevents command execution and forces backend call path
            modified_messages = self._filter_commands_from_messages(
                request_data.messages, context
            )
            # Return filtered messages so they're used in the backend call
            return ProcessedResult(
                command_executed=False,
                modified_messages=modified_messages,
                command_results=[],
            )

        # The command processor is now responsible for creating copies of any messages it modifies.
        return await self._command_processor.process_messages(
            request_data.messages, session_id, context
        )

    def _should_process_command_only(self, command_result: ProcessedResult) -> bool:
        """Determine if we should process command result without backend call."""
        return command_result.command_executed and not command_result.modified_messages

    def _filter_commands_from_messages(
        self, messages: list, context: RequestContext
    ) -> list:
        """Filter commands from message content when commands are disabled.

        Args:
            messages: List of messages to filter
            context: Request context for accessing command prefix

        Returns:
            List of messages with commands removed from content
        """
        from src.core.commands.parser import CommandParser
        from src.core.domain.chat import ChatMessage

        # Get command prefix from app_state or context
        command_prefix = "!/"  # default
        if self._app_state is not None:
            try:
                prefix = self._app_state.get_command_prefix()
                if prefix and isinstance(prefix, str):
                    command_prefix = prefix
            except (AttributeError, TypeError) as e:
                # Expected exceptions when get_command_prefix is unavailable or returns wrong type
                # Fallback to default prefix
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Could not get command prefix from app_state: %s", e, exc_info=False
                    )
            except Exception as e:
                # Unexpected errors - log with full context for visibility
                # Still fallback to default prefix to preserve fail-open behavior
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error getting command prefix from app_state: %s",
                        e,
                        exc_info=True,
                    )

        parser = CommandParser(command_prefix=command_prefix)
        filtered_messages = []

        for message in messages:
            if not isinstance(message, ChatMessage):
                filtered_messages.append(message)
                continue

            if not message.content or not isinstance(message.content, str):
                filtered_messages.append(message)
                continue

            # Parse commands in the content
            parsed_commands = parser.parse(
                message.content, command_prefix=command_prefix
            )

            if not parsed_commands:
                # No commands found, keep message as-is
                filtered_messages.append(message)
                continue

            # Remove all command matches from content
            # Build new content by keeping parts between commands
            content = message.content
            sorted_commands = sorted(parsed_commands, key=lambda x: x.start)

            # Build filtered content by keeping text between commands
            filtered_parts = []
            last_end = 0

            for parsed_cmd in sorted_commands:
                # Add text before this command
                if parsed_cmd.start > last_end:
                    filtered_parts.append(content[last_end : parsed_cmd.start])
                # Skip the command itself
                last_end = parsed_cmd.end

            # Add remaining text after last command
            if last_end < len(content):
                filtered_parts.append(content[last_end:])

            content = "".join(filtered_parts)

            # Create new message with filtered content
            filtered_message = message.model_copy(update={"content": content})
            filtered_messages.append(filtered_message)

        return filtered_messages
