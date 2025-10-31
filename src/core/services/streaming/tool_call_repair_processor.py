from __future__ import annotations

import logging
from typing import Any

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

        self._buffers: dict[str, dict[str, str]] = {}

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Processes a streaming content chunk, attempting to repair tool calls.
        """
        if content.is_empty and not content.is_done:
            return content  # Nothing to process

        stream_id = get_stream_id(content)
        state = self._buffers.get(stream_id, {"pending_text": ""})
        metadata = dict(content.metadata or {})
        detected_tool_calls: list[dict[str, Any]] = []

        chunk_text = content.content or ""
        reasoning_segments: list[str] = []
        for key in ("reasoning_content", "reasoning"):
            value = metadata.pop(key, None)
            if isinstance(value, str) and value:
                reasoning_segments.append(value)

        if reasoning_segments:
            state["pending_text"] += "".join(reasoning_segments)

        if chunk_text:
            state["pending_text"] += chunk_text

        repaired_content_parts: list[str] = []

        buffer_text = state["pending_text"]

        for marker in ("<use_mcp_tool", "<patch_file"):
            marker_index = buffer_text.find(marker)
            if marker_index > 0:
                prefix = buffer_text[:marker_index]
                if prefix.strip():
                    repaired_content_parts.append(prefix)
                buffer_text = buffer_text[marker_index:]
                state["pending_text"] = buffer_text
                break

        if buffer_text:
            repaired_json = self.tool_call_repair_service.repair_tool_calls(buffer_text)
            if repaired_json:
                detected_tool_calls.append(repaired_json)
                snippet = getattr(
                    self.tool_call_repair_service, "last_tool_snippet", None
                )
                if snippet:
                    idx = buffer_text.find(snippet)
                    if idx != -1:
                        prefix = buffer_text[:idx]
                        suffix = buffer_text[idx + len(snippet) :]
                        if prefix.strip():
                            repaired_content_parts.append(prefix)
                        buffer_text = suffix
                state["pending_text"] = buffer_text

        if not detected_tool_calls:
            trimmed = self._trim_buffer(state["pending_text"])
            if trimmed:
                repaired_content_parts.append(trimmed)
                state["pending_text"] = state["pending_text"][len(trimmed) :]

        if content.is_done:
            pending_text = state["pending_text"]
            if pending_text:
                synthetic_calls = (
                    ("<use_mcp_tool", "</use_mcp_tool>"),
                    ("<patch_file", "</patch_file>"),
                )
                handled = False
                for opener, closer in synthetic_calls:
                    if opener in pending_text and closer not in pending_text:
                        synthetic_buffer = pending_text + closer
                        repaired_json = self.tool_call_repair_service.repair_tool_calls(
                            synthetic_buffer
                        )
                        if repaired_json:
                            detected_tool_calls.append(repaired_json)
                            snippet = getattr(
                                self.tool_call_repair_service, "last_tool_snippet", None
                            )
                            if snippet:
                                idx = synthetic_buffer.find(snippet)
                                prefix = synthetic_buffer[:idx]
                                suffix = synthetic_buffer[idx + len(snippet) :]
                                if prefix.strip():
                                    repaired_content_parts.append(prefix)
                                if suffix.strip():
                                    repaired_content_parts.append(suffix)
                            handled = True
                            pending_text = ""
                            break
                if not handled and pending_text:
                    repaired_content_parts.append(pending_text)
            state["pending_text"] = ""

        if content.is_done or content.is_cancellation:
            self._buffers.pop(stream_id, None)
        else:
            if state["pending_text"]:
                self._buffers[stream_id] = state
            else:
                self._buffers.pop(stream_id, None)

        new_content_str = "".join(repaired_content_parts)
        if detected_tool_calls:
            logger.debug(
                "ToolCallRepairProcessor captured tool call(s): %s", detected_tool_calls
            )
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
