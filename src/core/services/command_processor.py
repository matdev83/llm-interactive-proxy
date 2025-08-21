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

    async def process_commands(
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
        disable_commands = False
        if context:
            # Use application state service instead of direct state access
            from src.core.services.application_state_service import (
                get_default_application_state,
            )
            
            app_state_service = get_default_application_state()
            disable_commands = (
                getattr(context.state, "disable_commands", False) or
                app_state_service.get_disable_interactive_commands()
            )

        if disable_commands:
            from src.core.domain.processed_result import ProcessedResult

            return ProcessedResult(
                command_executed=False, modified_messages=messages, command_results=[]
            )

        return await self._command_service.process_commands(messages, session_id)