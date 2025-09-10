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
        # In this simplified CommandProcessor for the interface,
        # we assume commands are always processed by the command service.
        # The disable_commands logic will be handled at a higher level (e.g., RequestProcessor).
        processed_result = await self._command_service.process_commands(
            messages,
            session_id,
        )
        return processed_result
