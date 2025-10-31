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
from src.core.services.streaming.stream_utils import get_stream_id

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

        self._buffers: dict[str, str] = {}

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Processes a streaming content chunk, attempting to repair tool calls.
        """
        if content.is_empty and not content.is_done:
            return content  # Nothing to process

        stream_id = get_stream_id(content)
        buffer = self._buffers.get(stream_id, "")
        metadata = dict(content.metadata or {})
        detected_tool_calls: list[dict[str, Any]] = []

        buffer += content.content or ""

        repaired_content_parts: list[str] = []

        if buffer:
            repaired_json = self.tool_call_repair_service.repair_tool_calls(buffer)
            if repaired_json:
                detected_tool_calls.append(repaired_json)
                buffer = ""
            else:
                flushed = self._trim_buffer(buffer)
                if flushed:
                    repaired_content_parts.append(flushed)
                    buffer = buffer[len(flushed) :]

        if content.is_done and buffer:
            repaired_content_parts.append(buffer)
            buffer = ""

        if buffer:
            self._buffers[stream_id] = buffer
        else:
            self._buffers.pop(stream_id, None)

        if content.is_done or content.is_cancellation:
            self._buffers.pop(stream_id, None)

        new_content_str = "".join(repaired_content_parts)
        if detected_tool_calls:
            existing_calls = metadata.get("tool_calls")
            if isinstance(existing_calls, list):
                metadata["tool_calls"] = existing_calls + detected_tool_calls
            else:
                metadata["tool_calls"] = detected_tool_calls
            metadata.setdefault("finish_reason", "tool_calls")

        if new_content_str or detected_tool_calls or content.is_done:
            return StreamingContent(
                content=new_content_str,
                is_done=content.is_done,
                is_cancellation=content.is_cancellation,
                metadata=metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        return StreamingContent(
            content="",
            is_cancellation=content.is_cancellation,
            metadata=metadata,
            usage=content.usage,
            raw_data=content.raw_data,
        )  # Return empty if nothing to yield

    def _trim_buffer(self, buffer: str) -> str:
        """Flush enough leading content to honor the buffer cap."""

        if not buffer:
            return ""

        encoded_length = len(buffer.encode("utf-8"))
        if encoded_length <= self._max_buffer_bytes:
            return ""

        overflow = encoded_length - self._max_buffer_bytes
        flushed_chars = []
        consumed = 0

        for ch in buffer:
            char_bytes = len(ch.encode("utf-8"))
            flushed_chars.append(ch)
            consumed += char_bytes
            if consumed >= overflow:
                break

        flush_text = "".join(flushed_chars)

        logger.warning(
            "ToolCallRepairProcessor buffer exceeded %d bytes; flushed %d characters",
            self._max_buffer_bytes,
            len(flush_text),
        )

        return flush_text
