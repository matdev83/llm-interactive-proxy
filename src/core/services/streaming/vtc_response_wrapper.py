"""
VTC Response Stream Wrapper - Transform ProcessedResponse streams with VTC processing.

This module provides a wrapper that applies VTC (Virtual Tool Calling) detection
to AsyncIterator[ProcessedResponse] streams. It is designed for connectors like gemini_base
that yield ProcessedResponse objects directly rather than raw SSE data.

The wrapper:
1. Extracts text content from OpenAI-format ProcessedResponse chunks
2. Buffers until complete XML tool call patterns are detected
3. Parses XML to internal tool call format for logging/metrics
4. Passes content through UNCHANGED - VTC clients expect their original XML format

Note: Unlike the main VTC processors, this wrapper does NOT re-serialize tool calls.
VTC clients like KiloCode handle their own XML format (e.g., <execute_command>)
and expect it to pass through unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.vtc_xml_parser import (
    detect_complete_tool_call,
    has_partial_xml_pattern,
    parse_vtc_xml,
)

logger = logging.getLogger(__name__)


@dataclass
class VTCWrapperConfig:
    """Configuration for VTC response wrapper."""

    # Maximum buffer size in bytes before forced flush
    max_buffer_bytes: int = 64 * 1024

    # Whether to emit partial/incomplete XML on stream end
    emit_partial_on_done: bool = True


class VTCResponseStreamWrapper:
    """
    Wraps ProcessedResponse streams with VTC (Virtual Tool Calling) processing.

    This wrapper applies VTC transformation to streams of ProcessedResponse objects,
    handling XML tool call extraction and re-serialization. It is designed for use
    with connectors that produce ProcessedResponse objects directly (like gemini_base).

    The processing flow:
    1. Extract text from ProcessedResponse.content["choices"][0]["delta"]["content"]
    2. Buffer text until complete XML tool call patterns are detected
    3. Parse XML tool calls to internal format using vtc_xml_parser
    4. Serialize internal tool calls back to XML
    5. Create new ProcessedResponse with processed content

    For sessions with vtc_enabled=False, chunks pass through unchanged.
    """

    def __init__(
        self,
        vtc_enabled: bool = False,
        config: VTCWrapperConfig | None = None,
    ) -> None:
        """
        Initialize the VTC response stream wrapper.

        Args:
            vtc_enabled: Whether VTC processing is enabled for this stream.
            config: Optional configuration settings.
        """
        self._vtc_enabled = vtc_enabled
        self._config = config or VTCWrapperConfig()
        self._buffer = ""
        self._last_chunk_template: ProcessedResponse | None = None

    async def wrap(
        self,
        stream: AsyncIterator[ProcessedResponse],
    ) -> AsyncIterator[ProcessedResponse]:
        """
        Wrap a ProcessedResponse stream with VTC processing.

        Args:
            stream: The source stream of ProcessedResponse objects.

        Yields:
            ProcessedResponse objects with VTC transformations applied.
        """
        if not self._vtc_enabled:
            # Pass through unchanged
            async for chunk in stream:
                yield chunk
            return

        async for chunk in stream:
            processed = self._process_chunk(chunk)
            if processed is not None:
                yield processed

        # Flush any remaining buffer at end of stream
        if self._buffer:
            final_chunk = self._flush_buffer()
            if final_chunk is not None:
                yield final_chunk

    def _process_chunk(self, chunk: ProcessedResponse) -> ProcessedResponse | None:
        """
        Process a single chunk through VTC transformation.

        Args:
            chunk: The ProcessedResponse to process.

        Returns:
            Processed chunk, or None if buffering (chunk should be held).
        """
        # Save as template for creating new chunks
        self._last_chunk_template = chunk

        # Extract text content from OpenAI format
        text = self._extract_text(chunk)

        # Handle chunks without text content (e.g., final chunks, tool calls, etc.)
        if not text:
            # Non-text chunks pass through as-is
            # Buffer will be flushed at end of stream or when complete pattern found
            return chunk

        # Add to buffer
        self._buffer += text

        # Check buffer size limit
        if len(self._buffer.encode("utf-8")) > self._config.max_buffer_bytes:
            logger.warning(
                "VTC wrapper buffer exceeded max size (%d bytes), forcing flush",
                self._config.max_buffer_bytes,
            )
            return self._flush_buffer()

        # Check for complete XML tool call pattern
        if detect_complete_tool_call(self._buffer):
            return self._process_complete_pattern()

        # Check if we might have a partial pattern (still buffering)
        if has_partial_xml_pattern(self._buffer):
            logger.debug(
                "VTC wrapper buffering partial XML pattern (%d bytes)",
                len(self._buffer),
            )
            return None  # Continue buffering

        # No XML patterns - flush buffer as regular content
        return self._flush_buffer()

    def _extract_text(self, chunk: ProcessedResponse) -> str:
        """
        Extract text content from ProcessedResponse.content (OpenAI format).

        Args:
            chunk: The ProcessedResponse to extract text from.

        Returns:
            The text content, or empty string if not found.
        """
        content = chunk.content
        if not isinstance(content, dict):
            return ""

        choices = content.get("choices", [])
        if not choices or not isinstance(choices, list):
            return ""

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return ""

        delta = first_choice.get("delta", {})
        if not isinstance(delta, dict):
            return ""

        text_content = delta.get("content", "")
        return text_content if isinstance(text_content, str) else ""

    def _inject_text(
        self, chunk: ProcessedResponse, new_text: str
    ) -> ProcessedResponse:
        """
        Create a new ProcessedResponse with modified text content.

        Args:
            chunk: The original ProcessedResponse to use as template.
            new_text: The new text content to inject.

        Returns:
            New ProcessedResponse with the modified text.
        """
        content = chunk.content
        if not isinstance(content, dict):
            # Can't inject into non-dict content, create minimal structure
            return ProcessedResponse(
                content={
                    "choices": [{"delta": {"content": new_text}}],
                },
                usage=chunk.usage,
                metadata=chunk.metadata,
            )

        # Deep copy the content structure
        new_content: dict[str, Any] = {}
        for key, value in content.items():
            if key != "choices":
                new_content[key] = value

        # Rebuild choices with new content
        choices = content.get("choices", [{}])
        new_choices = []

        for choice in choices:
            if not isinstance(choice, dict):
                new_choices.append(choice)
                continue

            new_choice: dict[str, Any] = {}
            for k, v in choice.items():
                if k != "delta":
                    new_choice[k] = v

            delta = choice.get("delta", {})
            if isinstance(delta, dict):
                new_delta = dict(delta)
                new_delta["content"] = new_text
                new_choice["delta"] = new_delta
            else:
                new_choice["delta"] = {"content": new_text}

            new_choices.append(new_choice)

        new_content["choices"] = new_choices

        return ProcessedResponse(
            content=new_content,
            usage=chunk.usage,
            metadata=dict(chunk.metadata) if chunk.metadata else {},
        )

    def _process_complete_pattern(self) -> ProcessedResponse:
        """
        Process a complete XML tool call pattern from the buffer.

        For VTC clients like KiloCode that use simple format (e.g., <execute_command>),
        we extract tool calls for internal processing (reactors, logging) but
        DO NOT modify the content - pass it through as-is.

        Returns:
            ProcessedResponse with VTC-processed content.
        """
        # Save original buffer content before any processing
        buffer_content = self._buffer
        self._buffer = ""

        # Parse XML tool calls from buffer for internal use (logging, metrics, reactors)
        # But we will NOT modify the content - pass through as-is for VTC clients
        tool_calls, _ = parse_vtc_xml(buffer_content, allowed_tools=None)

        if tool_calls:
            logger.info(
                "VTC wrapper detected %d tool call(s): %s",
                len(tool_calls),
                [tc.get("function", {}).get("name", "unknown") for tc in tool_calls],
            )
        else:
            logger.debug("VTC wrapper found no tool calls in complete pattern")

        # Return original content unchanged - VTC clients expect their original format
        return self._create_chunk_with_text(buffer_content)

    def _flush_buffer(self) -> ProcessedResponse | None:
        """
        Flush the buffer and return its content as a ProcessedResponse.

        For VTC clients, content is passed through unchanged - we only extract
        tool calls for internal processing (logging, metrics).

        Returns:
            ProcessedResponse with buffered content, or None if buffer is empty.
        """
        if not self._buffer:
            return None

        # Save original buffer content
        buffer_content = self._buffer
        self._buffer = ""

        # Try to extract any tool calls for logging/internal use
        tool_calls, _ = parse_vtc_xml(buffer_content, allowed_tools=None)

        if tool_calls:
            logger.info(
                "VTC wrapper detected %d tool call(s) on flush: %s",
                len(tool_calls),
                [tc.get("function", {}).get("name", "unknown") for tc in tool_calls],
            )

        # Return original content unchanged - VTC clients expect their original format
        return self._create_chunk_with_text(buffer_content)

    def _create_chunk_with_text(self, text: str) -> ProcessedResponse:
        """
        Create a ProcessedResponse chunk with the given text.

        Args:
            text: The text content for the chunk.

        Returns:
            A new ProcessedResponse with the text content.
        """
        if self._last_chunk_template is not None:
            return self._inject_text(self._last_chunk_template, text)

        # Fallback: create minimal chunk structure
        return ProcessedResponse(
            content={
                "id": "chatcmpl-vtc",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": text}}],
            },
            metadata={},
        )

    def reset(self) -> None:
        """Reset the wrapper state for reuse."""
        self._buffer = ""
        self._last_chunk_template = None


async def wrap_processed_response_stream_with_vtc(
    stream: AsyncIterator[ProcessedResponse],
    vtc_enabled: bool = False,
    config: VTCWrapperConfig | None = None,
) -> AsyncIterator[ProcessedResponse]:
    """
    Convenience function to wrap a ProcessedResponse stream with VTC processing.

    This function creates a VTCResponseStreamWrapper and applies it to the stream.
    Use this when you need to apply VTC processing to a stream without managing
    the wrapper instance directly.

    Args:
        stream: The source stream of ProcessedResponse objects.
        vtc_enabled: Whether VTC processing is enabled.
        config: Optional configuration settings.

    Yields:
        ProcessedResponse objects with VTC transformations applied.

    Example:
        ```python
        async for chunk in wrap_processed_response_stream_with_vtc(
            stream_generator(),
            vtc_enabled=True,
        ):
            yield chunk
        ```
    """
    wrapper = VTCResponseStreamWrapper(vtc_enabled=vtc_enabled, config=config)
    async for chunk in wrapper.wrap(stream):
        yield chunk
