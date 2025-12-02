"""
VTC Pre-Processor - Converts XML tool calls to internal format.

This processor handles the first step of VTC processing:
1. Buffers streaming content until complete XML patterns are detected
2. Parses XML tool calls into internal OpenAI-compatible format
3. Strips XML from content, leaving only text for downstream processors

This processor is only active for sessions with vtc_enabled=True.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.vtc_xml_parser import (
    detect_complete_tool_call,
    has_partial_xml_pattern,
    parse_vtc_xml,
)

logger = logging.getLogger(__name__)


@dataclass
class VTCPreProcessorConfig:
    """Configuration for VTC pre-processor."""

    # Maximum buffer size in bytes before forced flush
    max_buffer_bytes: int = 64 * 1024

    # Minimum content to buffer before checking for patterns
    min_buffer_check: int = 10


class VTCPreProcessor(IStreamProcessor):
    """
    Stream processor that converts XML tool calls to internal format.

    For sessions with vtc_enabled=True in metadata, this processor:
    1. Buffers streaming chunks until complete XML tool call patterns are detected
    2. Extracts tool calls using parse_vtc_xml() and adds them to metadata
    3. Strips the XML from content so downstream processors see clean text
    4. Passes through content unchanged for non-VTC sessions

    This allows the core pipeline (loop detection, reactors, filters) to work
    with a unified internal tool call format regardless of client type.
    """

    def __init__(
        self,
        registry: StreamingContextRegistry,
        config: VTCPreProcessorConfig | None = None,
    ) -> None:
        """
        Initialize the VTC pre-processor.

        Args:
            registry: The streaming context registry for buffer state.
            config: Optional configuration settings.
        """
        self._registry = registry
        self._config = config or VTCPreProcessorConfig()

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Process streaming content, extracting XML tool calls for VTC sessions.

        Args:
            content: The streaming content chunk to process.

        Returns:
            Processed streaming content with tool calls in metadata.
        """
        # Check if VTC is enabled for this stream
        vtc_enabled = content.metadata.get("vtc_enabled", False)
        if not vtc_enabled:
            return content

        # Get stream ID for buffer lookup
        stream_id = content.stream_id or "anonymous-stream"

        # Handle done/empty chunks - flush any remaining buffer
        if content.is_done or content.is_cancellation:
            return self._flush_buffer(content, stream_id)

        # Get current buffer state
        buffer = self._registry.get_vtc_buffer(stream_id)

        # Get content as string
        chunk_text = self._get_content_text(content)
        if not chunk_text and not buffer.pending_text:
            return content

        # Add chunk to buffer
        buffer.pending_text += chunk_text

        # Check buffer size limit
        if len(buffer.pending_text) > self._config.max_buffer_bytes:
            logger.warning(
                "VTC buffer exceeded max size (%d bytes), forcing flush",
                self._config.max_buffer_bytes,
            )
            return self._flush_buffer(content, stream_id)

        # Check if we have a complete tool call pattern
        if detect_complete_tool_call(buffer.pending_text):
            return self._extract_and_emit(content, stream_id, buffer)

        # Check if we might have a partial pattern (still buffering)
        if has_partial_xml_pattern(buffer.pending_text):
            # Still buffering - return empty content to avoid partial output
            logger.debug(
                "VTC buffering partial XML pattern (%d bytes)",
                len(buffer.pending_text),
            )
            return StreamingContent(
                content="",
                metadata=content.metadata.copy(),
                is_done=False,
                is_empty=True,
                stream_id=content.stream_id,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        # No patterns detected - flush buffer as regular content
        return self._flush_buffer(content, stream_id)

    def _get_content_text(self, content: StreamingContent) -> str:
        """
        Extract text content from StreamingContent.

        Args:
            content: The streaming content.

        Returns:
            String content.
        """
        if isinstance(content.content, str):
            return content.content
        if isinstance(content.content, bytes):
            return content.content.decode("utf-8", errors="replace")
        if isinstance(content.content, dict):
            # Handle dict content - extract text if present
            text_value = content.content.get("content", "")
            return str(text_value) if text_value else ""
        return ""

    def _flush_buffer(
        self, content: StreamingContent, stream_id: str
    ) -> StreamingContent:
        """
        Flush the buffer and return content.

        Args:
            content: The original streaming content.
            stream_id: The stream identifier.

        Returns:
            Streaming content with flushed buffer.
        """
        buffer = self._registry.get_vtc_buffer(stream_id)

        if not buffer.pending_text:
            return content

        # Parse any remaining content for tool calls
        allowed_tools = buffer.allowed_tools
        tool_calls, cleaned_text = parse_vtc_xml(buffer.pending_text, allowed_tools)

        # Clear buffer
        buffer.pending_text = ""

        # Build new metadata with tool calls if found
        new_metadata = content.metadata.copy()
        if tool_calls:
            existing_calls = new_metadata.get("tool_calls", [])
            if isinstance(existing_calls, list):
                new_metadata["tool_calls"] = existing_calls + tool_calls
            else:
                new_metadata["tool_calls"] = tool_calls

            logger.debug(
                "VTC pre-processor extracted %d tool calls on flush", len(tool_calls)
            )

        return StreamingContent(
            content=cleaned_text,
            metadata=new_metadata,
            is_done=content.is_done,
            is_empty=not cleaned_text,
            stream_id=content.stream_id,
            is_cancellation=content.is_cancellation,
            usage=content.usage,
            raw_data=content.raw_data,
        )

    def _extract_and_emit(
        self,
        content: StreamingContent,
        stream_id: str,
        buffer: Any,
    ) -> StreamingContent:
        """
        Extract tool calls from buffer and emit content.

        Args:
            content: The original streaming content.
            stream_id: The stream identifier.
            buffer: The VTC buffer state.

        Returns:
            Streaming content with extracted tool calls.
        """
        allowed_tools = buffer.allowed_tools
        tool_calls, cleaned_text = parse_vtc_xml(buffer.pending_text, allowed_tools)

        # Clear buffer
        buffer.pending_text = ""

        # Build new metadata with tool calls
        new_metadata = content.metadata.copy()
        if tool_calls:
            existing_calls = new_metadata.get("tool_calls", [])
            if isinstance(existing_calls, list):
                new_metadata["tool_calls"] = existing_calls + tool_calls
            else:
                new_metadata["tool_calls"] = tool_calls

            logger.debug("VTC pre-processor extracted %d tool calls", len(tool_calls))

        return StreamingContent(
            content=cleaned_text,
            metadata=new_metadata,
            is_done=content.is_done,
            is_empty=not cleaned_text,
            stream_id=content.stream_id,
            is_cancellation=content.is_cancellation,
            usage=content.usage,
            raw_data=content.raw_data,
        )

    def reset(self) -> None:
        """Reset processor state for new stream."""
        # Registry handles per-stream state, nothing to reset here
