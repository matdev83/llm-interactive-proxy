from __future__ import annotations

import json
import logging

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)

logger = logging.getLogger(__name__)


class ToolCallRepairProcessor(IStreamProcessor):
    """
    Stream processor that uses ToolCallRepairService to detect and repair
    tool calls within streaming content.
    """

    def __init__(self, tool_call_repair_service: IToolCallRepairService) -> None:
        self.tool_call_repair_service = tool_call_repair_service
        self._buffer = ""  # Internal buffer for accumulating chunks

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Processes a streaming content chunk, attempting to repair tool calls.
        """
        if content.is_empty and not content.is_done:
            return content  # Nothing to process

        self._buffer += content.content

        repaired_content_parts: list[str] = []
        remaining_buffer = self._buffer

        while True:
            # Attempt to repair tool calls from the current buffer
            repaired_json = self.tool_call_repair_service.repair_tool_calls(
                remaining_buffer
            )

            if repaired_json:
                # If a tool call is repaired, it means the buffer contained a complete
                # or repairable tool call.
                # The repair_tool_calls method works on the entire string, so we need
                # to figure out what part of the buffer was consumed.
                # This is a simplification: assuming repair_tool_calls consumes the
                # entire relevant part. A more robust implementation might track
                # consumed length. For now, we assume if a repair happened, it consumed
                # the relevant part and the rest is trailing.

                # Find the start and end of the detected tool call in the buffer
                # This is tricky because repair_tool_calls returns the repaired JSON,
                # not the original span. For a simple approach, we'll assume the
                # repaired JSON replaces the *entire* buffer up to the point it was found.
                # A more precise approach would involve re-running regexes to find span.

                # For now, let's just emit the repaired JSON and clear the buffer
                # until a more precise span extraction is available.
                repaired_content_parts.append(json.dumps(repaired_json))
                remaining_buffer = (
                    ""  # Assuming the whole buffer was processed for this tool call
                )
                break  # Process one tool call at a time per chunk, or until buffer is empty
            else:
                # No tool call found in the current buffer
                break  # Break if no more tool calls can be repaired right now

        # If it's the final chunk, and there's anything left in the buffer,
        # it means no more tool calls will arrive, so emit the remaining content as is.
        if content.is_done and remaining_buffer:
            repaired_content_parts.append(remaining_buffer)
            remaining_buffer = ""  # All processed

        self._buffer = remaining_buffer  # Update buffer for next chunk

        # Combine repaired parts and create a new StreamingContent
        new_content_str = "".join(repaired_content_parts)
        if new_content_str or content.is_done:
            return StreamingContent(
                content=new_content_str,
                is_done=content.is_done,
                is_cancellation=content.is_cancellation,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
        else:
            return StreamingContent(
                content="",
                is_cancellation=content.is_cancellation,
            )  # Return empty if nothing to yield
