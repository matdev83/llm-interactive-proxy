from __future__ import annotations

import json
import logging

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService

logger = logging.getLogger(__name__)


class ToolCallRepairProcessor(IStreamProcessor):
    """
    A stream processor that detects and repairs tool calls within streaming content.
    """

    def __init__(self, tool_call_repair_service: ToolCallRepairService) -> None:
        self._tool_call_repair_service = tool_call_repair_service

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Processes a streaming content chunk, attempting to repair tool calls.

        Args:
            content: The streaming content chunk to process.

        Returns:
            The processed streaming content chunk, with tool calls repaired if found.
        """
        if not content.content:
            return content

        repaired_tool_call = self._tool_call_repair_service.repair_tool_calls(
            content.content
        )

        if repaired_tool_call:
            logger.debug(
                "Tool call repaired in streaming content: %s", repaired_tool_call
            )
            # Replace content with the JSON string of the repaired tool call
            return StreamingContent(
                content=json.dumps(repaired_tool_call),
                is_done=content.is_done,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
        return content
