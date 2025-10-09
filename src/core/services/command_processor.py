"""
Command processor implementation.

This module provides the implementation of the command processor interface.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.command_service_interface import ICommandService

logger = logging.getLogger(__name__)


class CommandProcessor(ICommandProcessor):
    """Implementation of the command processor interface."""

    def __init__(self, command_service: ICommandService) -> None:
        """Initialize the command processor.

        Args:
            command_service: The command service to use for processing commands
        """
        self._command_service = command_service

    async def process_messages(
        self,
        messages: list[Any],
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResult:
        """Process commands in messages.

        Args:
            messages: The messages to process
            session_id: The session ID
            context: Optional request context

        Returns:
            The result of processing commands
        """
        # To prevent unintended modifications of the message history, we only
        # process the last message for commands. The command service is responsible
        # for handling the actual command detection and execution logic.
        if not messages:
            return ProcessedResult(
                command_executed=False, modified_messages=[], command_results=[]
            )

        # We only process the last message for commands.
        last_message = messages[-1]
        processed_result = await self._command_service.process_commands(
            [last_message],
            session_id,
        )

        # If the last message was modified, we replace it in the original list.
        # Otherwise, we return the original messages, preserving the history.
        modified_tail = processed_result.modified_messages
        if processed_result.command_executed or modified_tail:
            # Merge the processed tail with the untouched history so command-only runs stay empty
            processed_result.modified_messages = messages[:-1] + modified_tail
        else:
            # No commands were found, keep the original messages list
            processed_result.modified_messages = messages

        return processed_result
