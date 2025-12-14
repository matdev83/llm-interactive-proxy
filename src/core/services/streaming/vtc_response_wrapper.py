"""
VTC Response Stream Wrapper - Transform ProcessedResponse streams with VTC processing.

This module provides a wrapper that applies VTC (Virtual Tool Calling) detection
to AsyncIterator[ProcessedResponse] streams. It is designed for connectors like gemini_base
that yield ProcessedResponse objects directly rather than raw SSE data.

The wrapper:
1. Extracts text content from OpenAI-format ProcessedResponse chunks
2. Buffers until complete XML tool call patterns are detected
3. Parses XML to internal tool call format
4. Adds tool calls to metadata for reactor processing
5. Invokes tool call reactor for detected calls
6. Passes content through UNCHANGED - VTC clients expect their original XML format

Note: Unlike the main VTC processors, this wrapper does NOT re-serialize tool calls.
VTC clients like KiloCode handle their own XML format (e.g., <execute_command>)
and expect it to pass through unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.vtc_xml_parser import (
    detect_complete_tool_call,
    has_partial_xml_pattern,
    parse_vtc_xml,
)

if TYPE_CHECKING:
    from src.core.interfaces.tool_call_reactor_interface import IToolCallReactor

logger = logging.getLogger(__name__)


@dataclass
class VTCWrapperConfig:
    """Configuration for VTC response wrapper."""

    # Maximum buffer size in bytes before forced flush
    max_buffer_bytes: int = 64 * 1024

    # Whether to emit partial/incomplete XML on stream end
    emit_partial_on_done: bool = True


_DEFAULT_BACKEND_STEERING_MESSAGE = (
    "A tool call was blocked by proxy policy. Do not repeat the blocked tool call. "
    "Respond to the user with a compliant approach that does not require tools."
)

_MAX_SWALLOWED_ORIGINAL_CONTENT_CHARS = 4000


def _truncate_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


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
        tool_call_reactor: IToolCallReactor | None = None,
        session_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the VTC response stream wrapper.

        Args:
            vtc_enabled: Whether VTC processing is enabled for this stream.
            config: Optional configuration settings.
            tool_call_reactor: Optional reactor for processing detected tool calls.
            session_id: Session ID for reactor context.
            context: Additional context for reactor processing.
        """
        self._vtc_enabled = vtc_enabled
        self._config = config or VTCWrapperConfig()
        self._buffer = ""
        self._last_chunk_template: ProcessedResponse | None = None
        self._tool_call_reactor = tool_call_reactor
        self._session_id = session_id or ""
        self._context = context or {}

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
        import contextlib

        try:
            if not self._vtc_enabled:
                # Pass through unchanged
                async for chunk in stream:
                    yield chunk
                return

            async for chunk in stream:
                processed = await self._process_chunk_async(chunk)
                if processed is not None:
                    yield processed

            # Flush any remaining buffer at end of stream
            if self._buffer:
                final_chunk = await self._flush_buffer_async()
                if final_chunk is not None:
                    yield final_chunk
        except GeneratorExit:
            # Consumer cancelled - clean up the source stream
            if hasattr(stream, "aclose"):
                with contextlib.suppress(Exception):
                    await stream.aclose()
            raise

    async def _process_chunk_async(
        self, chunk: ProcessedResponse
    ) -> ProcessedResponse | None:
        """
        Process a single chunk through VTC transformation (async version).

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
            return await self._flush_buffer_async()

        # Check for complete XML tool call pattern
        if detect_complete_tool_call(self._buffer):
            return await self._process_complete_pattern_async()

        # Check if we might have a partial pattern (still buffering)
        if has_partial_xml_pattern(self._buffer):
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "VTC wrapper buffering partial XML pattern (%d bytes)",
                    len(self._buffer),
                )
            return None  # Continue buffering

        # No XML patterns - flush buffer as regular content
        return await self._flush_buffer_async()

    def _process_chunk(self, chunk: ProcessedResponse) -> ProcessedResponse | None:
        """
        Process a single chunk through VTC transformation (sync version for tests).

        Note: This sync version doesn't invoke the reactor. Use wrap() for full processing.

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
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
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
        # Use dict() to safely handle StopChunkWithUsage which raises on items()
        safe_content = dict(content)
        for key, value in safe_content.items():
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

    async def _invoke_reactor(
        self, tool_calls: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        """
        Invoke the tool call reactor for detected tool calls.

        This method processes tool calls through registered reactor handlers and
        collects any swallowed tool calls along with their replacement messages.

        Args:
            tool_calls: List of detected tool calls in internal format.

        Returns:
            Tuple of (non_swallowed_tool_calls, replacement_message, swallowed_any).
            - non_swallowed_tool_calls: Tool calls that were NOT swallowed by handlers
            - replacement_message: Combined replacement message for swallowed calls, or None
            - swallowed_any: True if any tool call was swallowed (even with empty message)
        """
        if not self._tool_call_reactor or not tool_calls:
            return tool_calls, None, False

        non_swallowed: list[dict[str, Any]] = []
        replacement_messages: list[str] = []
        swallowed_any = False

        try:
            import json as json_module

            from src.core.interfaces.tool_call_reactor_interface import ToolCallContext

            for tool_call in tool_calls:
                func_info = tool_call.get("function", {})
                tool_name = func_info.get("name", "unknown")
                tool_args = func_info.get("arguments", "{}")

                # Parse arguments if they're a JSON string
                if isinstance(tool_args, str):
                    try:
                        tool_args = json_module.loads(tool_args)
                    except json_module.JSONDecodeError:
                        tool_args = {"raw": tool_args}

                # Build a minimal response representation for the reactor context
                # The full_response is required by ToolCallContext
                full_response = {
                    "tool_calls": [tool_call],
                    "vtc_source": True,  # Mark as coming from VTC extraction
                }

                context = ToolCallContext(
                    session_id=self._session_id,
                    tool_name=tool_name,
                    tool_arguments=tool_args,
                    backend_name=self._context.get("backend_name", "unknown"),
                    model_name=self._context.get("model_name", "unknown"),
                    full_response=full_response,
                    calling_agent=self._context.get("calling_agent"),
                )

                logger.debug(
                    "VTC wrapper invoking reactor for tool call: %s (session: %s)",
                    tool_name,
                    self._session_id,
                )

                # Invoke reactor and handle the result
                result = await self._tool_call_reactor.process_tool_call(context)

                if result and result.should_swallow:
                    # Tool call was swallowed by a handler
                    logger.info(
                        "VTC tool call '%s' swallowed by reactor (session: %s)",
                        tool_name,
                        self._session_id,
                    )
                    swallowed_any = True
                    if (
                        isinstance(result.replacement_response, str)
                        and result.replacement_response.strip()
                    ):
                        replacement_messages.append(result.replacement_response.strip())
                else:
                    # Tool call was not swallowed, keep it
                    non_swallowed.append(tool_call)

        except Exception as e:
            logger.warning(
                "VTC wrapper failed to invoke reactor: %s",
                e,
                exc_info=True,
            )
            # On error, return original tool calls unchanged
            return tool_calls, None, False

        # Combine replacement messages if any
        combined_replacement = (
            "\n\n".join(replacement_messages) if replacement_messages else None
        )

        return non_swallowed, combined_replacement, swallowed_any

    async def _process_complete_pattern_async(self) -> ProcessedResponse:
        """
        Process a complete XML tool call pattern from the buffer (async version).

        For VTC clients, we extract tool calls and process them through the reactor.
        If any tool calls are swallowed (e.g., blocked by access control), we:
        1. Strip the XML for swallowed tool calls from the content
        2. Insert the replacement message from the handler

        Returns:
            ProcessedResponse with VTC-processed content and tool calls in metadata.
        """
        # Save original buffer content before any processing
        buffer_content = self._buffer
        self._buffer = ""

        # Parse XML tool calls from buffer for internal use (reactors, logging, metrics)
        # We get both the parsed tool calls AND the cleaned content (XML stripped)
        tool_calls, cleaned_content = parse_vtc_xml(buffer_content, allowed_tools=None)

        if tool_calls:
            logger.info(
                "VTC wrapper detected %d tool call(s): %s",
                len(tool_calls),
                [tc.get("function", {}).get("name", "unknown") for tc in tool_calls],
            )
            # Invoke reactor for detected tool calls and handle swallowing
            non_swallowed, replacement_msg, swallowed_any = await self._invoke_reactor(
                tool_calls
            )

            # If any tool calls were swallowed, strip tool XML and mark for backend retry.
            # IMPORTANT: Never inject steering/replacement messages into client-visible output.
            if swallowed_any:
                output_content = cleaned_content.strip()

                logger.info(
                    "VTC wrapper: %d tool call(s) swallowed, %d passed through",
                    len(tool_calls) - len(non_swallowed),
                    len(non_swallowed),
                )

                return self._create_chunk_with_text(
                    output_content,
                    swallowed=True,
                    swallowed_count=len(tool_calls) - len(non_swallowed),
                    extra_metadata={
                        "tool_call_swallowed": True,
                        "steering_message": (
                            replacement_msg
                            if isinstance(replacement_msg, str)
                            and replacement_msg.strip()
                            else _DEFAULT_BACKEND_STEERING_MESSAGE
                        ),
                        "swallowed_tool_calls": tool_calls,
                        "swallowed_original_content": _truncate_text(
                            buffer_content,
                            _MAX_SWALLOWED_ORIGINAL_CONTENT_CHARS,
                        ),
                        "_steering_replacement": True,
                    },
                )

            # No tool calls were swallowed - return original content unchanged
            return self._create_chunk_with_text(buffer_content, tool_calls=tool_calls)
        else:
            logger.debug("VTC wrapper found no tool calls in complete pattern")

        # No tool calls found - return original content unchanged
        return self._create_chunk_with_text(buffer_content, tool_calls=tool_calls)

    def _process_complete_pattern(self) -> ProcessedResponse:
        """
        Process a complete XML tool call pattern from the buffer (sync version).

        Note: This sync version doesn't invoke the reactor. Use the async
        wrap() method to ensure reactor invocation.

        Returns:
            ProcessedResponse with VTC-processed content and tool calls in metadata.
        """
        # Save original buffer content before any processing
        buffer_content = self._buffer
        self._buffer = ""

        # Parse XML tool calls from buffer for internal use (reactors, logging, metrics)
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
        # Tool calls are added to metadata for reactor processing
        return self._create_chunk_with_text(buffer_content, tool_calls=tool_calls)

    async def _flush_buffer_async(self) -> ProcessedResponse | None:
        """
        Flush the buffer and return its content as a ProcessedResponse (async version).

        For VTC clients, we extract tool calls and process them through the reactor.
        If any tool calls are swallowed, we modify the content accordingly.

        Returns:
            ProcessedResponse with buffered content and any detected tool calls,
            or None if buffer is empty.
        """
        if not self._buffer:
            return None

        # Save original buffer content
        buffer_content = self._buffer
        self._buffer = ""

        # Try to extract any tool calls for reactor processing
        tool_calls, cleaned_content = parse_vtc_xml(buffer_content, allowed_tools=None)

        if tool_calls:
            logger.info(
                "VTC wrapper detected %d tool call(s) on flush: %s",
                len(tool_calls),
                [tc.get("function", {}).get("name", "unknown") for tc in tool_calls],
            )
            # Invoke reactor for detected tool calls and handle swallowing
            non_swallowed, replacement_msg, swallowed_any = await self._invoke_reactor(
                tool_calls
            )

            # If any tool calls were swallowed, strip tool XML and mark for backend retry.
            # IMPORTANT: Never inject steering/replacement messages into client-visible output.
            if swallowed_any:
                output_content = cleaned_content.strip()

                logger.info(
                    "VTC wrapper flush: %d tool call(s) swallowed, %d passed through",
                    len(tool_calls) - len(non_swallowed),
                    len(non_swallowed),
                )

                return self._create_chunk_with_text(
                    output_content,
                    swallowed=True,
                    swallowed_count=len(tool_calls) - len(non_swallowed),
                    extra_metadata={
                        "tool_call_swallowed": True,
                        "steering_message": (
                            replacement_msg
                            if isinstance(replacement_msg, str)
                            and replacement_msg.strip()
                            else _DEFAULT_BACKEND_STEERING_MESSAGE
                        ),
                        "swallowed_tool_calls": tool_calls,
                        "swallowed_original_content": _truncate_text(
                            buffer_content,
                            _MAX_SWALLOWED_ORIGINAL_CONTENT_CHARS,
                        ),
                        "_steering_replacement": True,
                    },
                )

            # No tool calls were swallowed - return original content unchanged
            return self._create_chunk_with_text(buffer_content, tool_calls=tool_calls)

        # No tool calls found - return original content unchanged
        return self._create_chunk_with_text(buffer_content, tool_calls=tool_calls)

    def _flush_buffer(self) -> ProcessedResponse | None:
        """
        Flush the buffer and return its content as a ProcessedResponse (sync version).

        Note: This sync version doesn't invoke the reactor. Use wrap() for full processing.

        Returns:
            ProcessedResponse with buffered content and any detected tool calls,
            or None if buffer is empty.
        """
        if not self._buffer:
            return None

        # Save original buffer content
        buffer_content = self._buffer
        self._buffer = ""

        # Try to extract any tool calls for reactor processing
        tool_calls, _ = parse_vtc_xml(buffer_content, allowed_tools=None)

        if tool_calls:
            logger.info(
                "VTC wrapper detected %d tool call(s) on flush: %s",
                len(tool_calls),
                [tc.get("function", {}).get("name", "unknown") for tc in tool_calls],
            )

        # Return original content unchanged - VTC clients expect their original format
        # Tool calls are added to metadata for reactor processing
        return self._create_chunk_with_text(buffer_content, tool_calls=tool_calls)

    def _create_chunk_with_text(
        self,
        text: str,
        tool_calls: list[dict[str, Any]] | None = None,
        swallowed: bool = False,
        swallowed_count: int = 0,
        extra_metadata: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        """
        Create a ProcessedResponse chunk with the given text and optional tool calls.

        Args:
            text: The text content for the chunk.
            tool_calls: Optional list of detected tool calls to add to metadata.
            swallowed: Whether any tool calls were swallowed by handlers.
            swallowed_count: Number of tool calls that were swallowed.

        Returns:
            A new ProcessedResponse with the text content and tool calls in metadata.
        """
        # Build metadata with tool calls for reactor processing
        metadata: dict[str, Any] = {}
        if tool_calls:
            metadata["tool_calls"] = tool_calls
            # Mark as VTC-sourced so reactors know these came from XML parsing
            metadata["vtc_tool_calls"] = True

        # Track swallowing for downstream processors
        if swallowed:
            metadata["vtc_tool_calls_swallowed"] = True
            metadata["vtc_swallowed_count"] = swallowed_count

        if extra_metadata:
            metadata.update(extra_metadata)

        if self._last_chunk_template is not None:
            chunk = self._inject_text(self._last_chunk_template, text)
            # Merge metadata into the chunk
            if metadata:
                if chunk.metadata:
                    # Merge all metadata fields
                    chunk.metadata.update(metadata)
                else:
                    # Create new chunk with metadata
                    chunk = ProcessedResponse(
                        content=chunk.content,
                        usage=chunk.usage,
                        metadata=metadata,
                    )
            return chunk

        # Fallback: create minimal chunk structure
        return ProcessedResponse(
            content={
                "id": "chatcmpl-vtc",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": text}}],
            },
            metadata=metadata,
        )

    def reset(self) -> None:
        """Reset the wrapper state for reuse."""
        self._buffer = ""
        self._last_chunk_template = None


async def wrap_processed_response_stream_with_vtc(
    stream: AsyncIterator[ProcessedResponse],
    vtc_enabled: bool = False,
    config: VTCWrapperConfig | None = None,
    tool_call_reactor: IToolCallReactor | None = None,
    session_id: str | None = None,
    context: dict[str, Any] | None = None,
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
        tool_call_reactor: Optional reactor for processing detected tool calls.
        session_id: Session ID for reactor context.
        context: Additional context for reactor processing.

    Yields:
        ProcessedResponse objects with VTC transformations applied.

    Example:
        ```python
        async for chunk in wrap_processed_response_stream_with_vtc(
            stream_generator(),
            vtc_enabled=True,
            tool_call_reactor=reactor,
            session_id="sess-123",
        ):
            yield chunk
        ```
    """
    import contextlib

    wrapper = VTCResponseStreamWrapper(
        vtc_enabled=vtc_enabled,
        config=config,
        tool_call_reactor=tool_call_reactor,
        session_id=session_id,
        context=context,
    )
    try:
        async for chunk in wrapper.wrap(stream):
            yield chunk
    except GeneratorExit:
        # Consumer cancelled - close the wrapper's stream
        if hasattr(stream, "aclose"):
            with contextlib.suppress(Exception):
                await stream.aclose()
        raise
