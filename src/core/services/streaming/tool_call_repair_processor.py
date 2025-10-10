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

    def __init__(
        self,
        tool_call_repair_service: IToolCallRepairService,
        *,
        max_buffer_bytes: int | None = None,
    ) -> None:
        self.tool_call_repair_service = tool_call_repair_service
        service_cap = getattr(tool_call_repair_service, "max_buffer_bytes", None)
        if max_buffer_bytes is not None:
            self._max_buffer_bytes = max_buffer_bytes
        elif isinstance(service_cap, int):
            self._max_buffer_bytes = service_cap
        else:
            self._max_buffer_bytes = 64 * 1024

        self._buffer = ""  # Internal buffer for accumulating chunks

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Processes a streaming content chunk, attempting to repair tool calls.
        """
        if content.is_empty and not content.is_done:
            return content  # Nothing to process

        incoming_text = content.content or ""
        if incoming_text:
            self._buffer += incoming_text

        repaired_content_parts: list[str] = []

        if self._buffer:
            repaired_json = self.tool_call_repair_service.repair_tool_calls(
                self._buffer
            )
            if repaired_json:
                repaired_content_parts.append(json.dumps(repaired_json))
                self._buffer = ""
            else:
                flushed = self._trim_buffer()
                if flushed:
                    repaired_content_parts.append(flushed)

        if content.is_done and self._buffer:
            repaired_content_parts.append(self._buffer)
            self._buffer = ""

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

        return StreamingContent(
            content="",
            is_cancellation=content.is_cancellation,
        )  # Return empty if nothing to yield

    def _trim_buffer(self) -> str:
        """Flush enough leading content to honor the buffer cap."""

        if not self._buffer:
            return ""

        encoded_length = len(self._buffer.encode("utf-8"))
        if encoded_length <= self._max_buffer_bytes:
            return ""

        overflow = encoded_length - self._max_buffer_bytes
        flushed_chars = []
        consumed = 0

        for ch in self._buffer:
            char_bytes = len(ch.encode("utf-8"))
            flushed_chars.append(ch)
            consumed += char_bytes
            if consumed >= overflow:
                break

        flush_text = "".join(flushed_chars)
        self._buffer = self._buffer[len(flush_text) :]

        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "ToolCallRepairProcessor buffer exceeded %d bytes; flushed %d characters",
                self._max_buffer_bytes,
                len(flush_text),
            )

        return flush_text
