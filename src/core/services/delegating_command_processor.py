from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.chat import ChatMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_processor_interface import ICommandProcessor

if TYPE_CHECKING:
    from src.core.domain.request_context import RequestContext


logger = logging.getLogger(__name__)


class DelegatingCommandProcessor(ICommandProcessor):
    """A command processor that delegates to other processors based on message content."""

    def __init__(
        self,
        text_command_processor: ICommandProcessor,
        tool_call_command_processor: ICommandProcessor,
    ) -> None:
        self._text_command_processor = text_command_processor
        self._tool_call_command_processor = tool_call_command_processor

    async def process_messages(
        self,
        messages: list[ChatMessage],
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResult:
        """
        Process commands by delegating to the appropriate processor.

        If assistant messages with tool_calls are present, use the tool_call_command_processor.
        Otherwise, fall back to the text_command_processor.
        """
        if any(
            (
                message.tool_calls
                and isinstance(message.tool_calls, list)
                and len(message.tool_calls) > 0
            )
            for message in messages
            if message.role == "assistant"
        ):
            logger.debug("Delegating to ToolCallCommandProcessor")
            return await self._tool_call_command_processor.process_messages(
                messages, session_id, context
            )

        logger.debug("Delegating to CommandProcessor (text-based)")
        return await self._text_command_processor.process_messages(
            messages, session_id, context
        )
