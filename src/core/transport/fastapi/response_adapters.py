"""
FastAPI response adapters.

This module provides backward-compatible public API for response adaptation.
All logic is delegated to focused layer modules under adapters/.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

from fastapi.responses import Response
from starlette.responses import StreamingResponse

from src.core.domain.chat import ChatResponse, StreamingChatResponse
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.wire_capture_interface import IWireCapture

# Import SSEAssembler for streaming conversion
from src.core.ports.sse_assembler import SSEAssembler

# Import layer implementations
from src.core.transport.fastapi.adapters.capture.wire_capture_coordinator import (
    WireCaptureCoordinator,
)
from src.core.transport.fastapi.adapters.response.json_response_builder import (
    JSONResponseBuilder,
)
from src.core.transport.fastapi.adapters.response.other_response_builder import (
    OtherResponseBuilder,
)
from src.core.transport.fastapi.adapters.response.streaming_response_builder import (
    StreamingResponseBuilder,
)
from src.core.transport.fastapi.adapters.streaming.content_converter import (
    StreamingContentConverter,
)
from src.core.transport.fastapi.adapters.usage.header_injector import (
    UsageHeaderInjector,
)

T = TypeVar("T")

# Lazy singleton instances
_json_builder: JSONResponseBuilder | None = None
_streaming_builder: StreamingResponseBuilder | None = None
_other_builder: OtherResponseBuilder | None = None
_content_converter: StreamingContentConverter | None = None
_sse_assembler: SSEAssembler | None = None
_wire_capture_coordinator: WireCaptureCoordinator | None = None
_usage_header_injector: UsageHeaderInjector | None = None


def _resolve_service(service_type: type[T]) -> T | None:
    """Resolve a service from DI if available.

    Returns None when DI is unavailable or service is not registered.
    """
    try:
        from src.core.di.services import get_service_provider

        provider = get_service_provider()
        return provider.get_service(service_type)
    except Exception:
        return None


def _get_usage_header_injector() -> UsageHeaderInjector:
    """Get or create usage header injector singleton."""
    global _usage_header_injector
    if _usage_header_injector is None:
        _usage_header_injector = (
            _resolve_service(UsageHeaderInjector) or UsageHeaderInjector()
        )
    return _usage_header_injector


def _apply_usage_headers(
    headers: dict[str, str] | None,
    usage: dict[str, object] | None,
) -> dict[str, str]:
    """Backward-compatible helper to inject usage headers.

    Some tests (and legacy code) import this helper directly. The implementation
    lives in the adapter layer (UsageHeaderInjector), so we keep a thin wrapper
    here to preserve the old public surface.
    """
    if headers is None:
        headers = {}
    if usage is None:
        return dict(headers)
    return _get_usage_header_injector().inject_headers(dict(headers), usage)


def _get_json_builder() -> JSONResponseBuilder:
    """Get or create JSON response builder singleton."""
    global _json_builder
    if _json_builder is None:
        _json_builder = _resolve_service(JSONResponseBuilder) or JSONResponseBuilder()
    return _json_builder


def _get_streaming_builder() -> StreamingResponseBuilder:
    """Get or create streaming response builder singleton."""
    global _streaming_builder
    if _streaming_builder is None:
        _streaming_builder = (
            _resolve_service(StreamingResponseBuilder) or StreamingResponseBuilder()
        )
    return _streaming_builder


def _get_other_builder() -> OtherResponseBuilder:
    """Get or create other response builder singleton."""
    global _other_builder
    if _other_builder is None:
        _other_builder = (
            _resolve_service(OtherResponseBuilder) or OtherResponseBuilder()
        )
    return _other_builder


def _get_content_converter() -> StreamingContentConverter:
    """Get or create streaming content converter singleton."""
    global _content_converter
    if _content_converter is None:
        _content_converter = (
            _resolve_service(StreamingContentConverter) or StreamingContentConverter()
        )
    return _content_converter


def _get_sse_assembler() -> SSEAssembler:
    """Get or create SSE assembler singleton."""
    global _sse_assembler
    if _sse_assembler is None:
        _sse_assembler = _resolve_service(SSEAssembler) or SSEAssembler()
    return _sse_assembler


def _get_wire_capture_coordinator(
    wire_capture: IWireCapture | None,
) -> WireCaptureCoordinator:
    """Get or create wire capture coordinator singleton."""
    global _wire_capture_coordinator
    if _wire_capture_coordinator is None:
        _wire_capture_coordinator = WireCaptureCoordinator(wire_capture=wire_capture)
    elif wire_capture is not None:
        # Update wire capture if provided
        _wire_capture_coordinator = WireCaptureCoordinator(wire_capture=wire_capture)
    return _wire_capture_coordinator


def _normalize_response_envelope(
    domain_response: (
        ResponseEnvelope | StreamingResponseEnvelope | ProcessedResponse | ChatResponse
    ),
) -> ResponseEnvelope:
    """Normalize various response types to ResponseEnvelope."""
    if isinstance(domain_response, ResponseEnvelope):
        return domain_response
    elif isinstance(domain_response, ChatResponse):
        return ResponseEnvelope(
            content=domain_response.model_dump(),
            headers=None,
            status_code=200,
            usage=domain_response.usage,
            metadata=(
                {"model": domain_response.model} if domain_response.model else None
            ),
        )
    elif isinstance(domain_response, ProcessedResponse):
        return ResponseEnvelope(
            content=domain_response.content,
            headers=None,
            status_code=200,
            usage=domain_response.usage,
            metadata=domain_response.metadata,
        )
    elif isinstance(domain_response, dict):
        return ResponseEnvelope(content=domain_response, headers=None, status_code=200)
    else:
        return ResponseEnvelope(content=domain_response, headers=None, status_code=200)


def _apply_content_converter(
    content: Any, converter: Callable[[Any], Any] | None
) -> Any:
    """Apply content converter if provided."""
    if converter:
        return converter(content)
    return content


async def _string_to_async_iterator(content: bytes) -> AsyncIterator[ProcessedResponse]:
    """Convert a bytes object to an async iterator that yields the content once."""
    yield ProcessedResponse(content=content.decode("utf-8"))


def _chunk_signals_done(content: Any, metadata: dict[str, Any] | None) -> bool:
    """Detect if a streaming chunk signals end-of-stream.

    This function is kept here because it's imported by content_converter.py.
    """

    def _has_meaningful_payload(payload: Any) -> bool:
        """Check whether a chunk carries assistant content, tool calls, or usage."""
        if payload is None:
            return False

        if isinstance(payload, dict):
            usage_block = payload.get("usage")
            if isinstance(usage_block, dict):
                return True

            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    delta = first_choice.get("delta") or first_choice.get("message")
                    if isinstance(delta, dict) and any(
                        delta.get(key)
                        for key in (
                            "content",
                            "tool_calls",
                            "reasoning_content",
                            "reasoning",
                        )
                    ):
                        return True

            return bool(payload)

        return bool(payload)

    text_value: str | None = None
    if isinstance(content, bytes | bytearray):
        text_value = content.decode("utf-8", errors="ignore").strip()
    elif isinstance(content, str):
        text_value = content.strip()

    if text_value:
        if text_value == "[DONE]":
            return True
        if text_value == '["DONE"]':
            return True
        if text_value.startswith("data: [DONE]"):
            return True
        if text_value.startswith('data: ["DONE"]'):
            return True

    normalized_event: str | None = None
    if metadata:
        event_type = metadata.get("event_type")
        if isinstance(event_type, str):
            normalized_event = event_type.strip().lower()

    # Honor explicit done markers propagated via metadata
    if metadata and metadata.get("is_done") is True:
        return True

    # Check for finish_reason in content (OpenAI-style chunks)
    if isinstance(content, dict):
        finish_reason = content.get("finish_reason")
        if finish_reason:
            return True

        # Check finish_reason in choices
        choices = content.get("choices")
        if isinstance(choices, list) and choices:
            for choice in choices:
                if isinstance(choice, dict):
                    choice_finish = choice.get("finish_reason")
                    if choice_finish:
                        return True

    # Treat explicit terminal events as done only when the chunk is otherwise empty
    return normalized_event in {
        "message.done",
        "completion",
        "done",
    } and not _has_meaningful_payload(content)


def to_fastapi_response(
    domain_response: Any,
    content_converter: Callable[[Any], Any] | None = None,
    *,
    wire_capture: IWireCapture | None = None,
    context: RequestContext | None = None,
) -> Response:
    """Convert a domain response envelope to a FastAPI response.

    Args:
        domain_response: The domain response envelope
        content_converter: Optional function to convert the content
            before creating the response
        wire_capture: Optional wire capture instance
        context: Optional request context

    Returns:
        A FastAPI response
    """
    envelope = _normalize_response_envelope(domain_response)

    # Apply content converter if provided (legacy support)
    if content_converter:
        envelope = ResponseEnvelope(
            content=_apply_content_converter(envelope.content, content_converter),
            headers=envelope.headers,
            status_code=envelope.status_code,
            usage=envelope.usage,
            metadata=envelope.metadata,
        )

    # Determine media type
    media_type = getattr(envelope, "media_type", "application/json")

    # Build appropriate response
    response: Response
    if media_type and media_type.startswith("application/json"):
        response = _get_json_builder().build(envelope, context=context)
        # Extract content for wire capture (JSONResponse stores content in body as bytes)
        response_content = envelope.content
        if content_converter:
            response_content = _apply_content_converter(
                response_content, content_converter
            )
    else:
        response = _get_other_builder().build(envelope)
        response_content = envelope.content

    # Schedule wire capture for non-streaming responses
    if wire_capture:
        coordinator = _get_wire_capture_coordinator(wire_capture)
        coordinator.schedule_capture(envelope, response_content, context=context)

    return response


def to_fastapi_streaming_response(
    domain_response: StreamingResponseEnvelope,
    *,
    wire_capture: IWireCapture | None = None,
    context: RequestContext | None = None,
) -> StreamingResponse:
    """Convert a domain streaming response envelope to a FastAPI streaming response.

    This function uses StreamingContentConverter and SSEAssembler to convert
    raw stream chunks to SSE format.

    XML Leakage Prevention:
    -----------------------
    This function prevents XML tool tag leakage by using ToolBlockBuffer within
    StreamingContentConverter. The buffer tracks detected tool tags dynamically
    via the streaming context registry (tracked_tags), ensuring multiline XML
    tool blocks are buffered until complete before emission. This prevents
    partial tool tags from leaking to clients. The sanitize_multiline_tool_blocks
    method in StreamingContentConverter handles the actual buffering logic via
    _apply_tag_buffer operations that hold partial tags until completion.

    Args:
        domain_response: The domain streaming response envelope
        wire_capture: Optional wire capture instance
        context: Optional request context

    Returns:
        A FastAPI streaming response
    """
    envelope_metadata = (
        domain_response.metadata if isinstance(domain_response.metadata, dict) else {}
    )

    content_iter = domain_response.content
    if content_iter is None:
        # Create empty iterator if content is None
        async def _empty_streamer() -> AsyncIterator[bytes]:
            return
            yield  # Make it an async generator

        return StreamingResponse(
            content=_empty_streamer(),
            media_type=getattr(domain_response, "media_type", "text/event-stream"),
            status_code=domain_response.status_code or 200,
            headers=domain_response.headers or {},
        )

    # Convert raw stream to StreamingContent using StreamingContentConverter
    converter = _get_content_converter()
    conversion_context = {
        "envelope_metadata": envelope_metadata,
        "context": context,
    }

    async def _convert_and_assemble() -> AsyncIterator[bytes]:
        """Convert raw stream to SSE bytes."""

        # Ensure async iterator
        async def _ensure_async_iterator(
            source: AsyncIterator[Any] | Any,
        ) -> AsyncIterator[Any]:
            try:
                if hasattr(source, "__aiter__"):
                    async for item in source:  # type: ignore[async-for]
                        yield item
                elif hasattr(source, "__iter__"):
                    # Handle sync iterables
                    for item in source:  # type: ignore[union-attr]
                        yield item
                else:
                    # Not iterable - treat as single item or raise error
                    # This handles Mock objects and other non-iterable types
                    raise TypeError(
                        f"Content must be an async iterator, sync iterator, or iterable, "
                        f"got {type(source).__name__}"
                    )
            except GeneratorExit:
                # Close the source iterator if it supports aclose
                if hasattr(source, "aclose"):
                    with contextlib.suppress(Exception):
                        await source.aclose()  # type: ignore[union-attr]
                raise

        async_stream = _ensure_async_iterator(content_iter)

        # Convert to StreamingContent (async generator returns iterator directly)
        streaming_content_iter = converter.convert_stream(
            async_stream, conversion_context
        )

        # Convert StreamingContent to SSE bytes
        assembler = _get_sse_assembler()
        sse_bytes_iter = assembler.assemble_stream(streaming_content_iter, format="sse")

        # Wrap stream for wire capture if enabled
        if wire_capture:
            coordinator = _get_wire_capture_coordinator(wire_capture)
            sse_bytes_iter = coordinator.wrap_stream(domain_response, sse_bytes_iter)

        try:
            async for sse_chunk in sse_bytes_iter:
                yield sse_chunk
                await asyncio.sleep(0)  # Yield to event loop
        except GeneratorExit:
            # Client disconnected - clean up the SSE iterator
            if hasattr(sse_bytes_iter, "aclose"):
                with contextlib.suppress(Exception):
                    await sse_bytes_iter.aclose()
            raise

    # Build streaming response
    return StreamingResponse(
        content=_convert_and_assemble(),
        media_type=getattr(domain_response, "media_type", "text/event-stream"),
        status_code=domain_response.status_code or 200,
        headers=domain_response.headers or {},
    )


def domain_response_to_fastapi(
    domain_response: Any,
    content_converter: Callable[[Any], Any] | None = None,
    *,
    wire_capture: IWireCapture | None = None,
    context: RequestContext | None = None,
) -> Response | StreamingResponse:
    """Convert any domain response to a FastAPI response.

    This function detects the type of domain response and calls the appropriate
    adapter function.

    Args:
        domain_response: The domain response envelope (streaming or non-streaming)
        content_converter: Optional function to convert the content for non-streaming
            responses before creating the response
        wire_capture: Optional wire capture instance
        context: Optional request context

    Returns:
        A FastAPI response (streaming or non-streaming)
    """
    # Detect streaming envelope by type name or class
    if (
        isinstance(domain_response, StreamingResponseEnvelope)
        or domain_response.__class__.__name__ == "StreamingResponseEnvelope"
    ):
        return to_fastapi_streaming_response(
            domain_response, wire_capture=wire_capture, context=context
        )

    # If it's a StreamingChatResponse, convert to StreamingResponseEnvelope
    if isinstance(domain_response, StreamingChatResponse):
        # Create a proper StreamingResponseEnvelope - StreamingChatResponse doesn't have
        # headers, status_code, or media_type attributes
        content_bytes = (
            str(domain_response.content).encode() if domain_response.content else b""
        )
        content_iterator = _string_to_async_iterator(content_bytes)

        return to_fastapi_streaming_response(
            StreamingResponseEnvelope(
                content=content_iterator, media_type="text/event-stream", headers={}
            ),
            wire_capture=wire_capture,
            context=context,
        )

    return to_fastapi_response(
        domain_response,
        content_converter,
        wire_capture=wire_capture,
        context=context,
    )


# Backward compatibility wrappers for test helpers
def _inject_reasoning_metadata(
    content: Any,
    metadata: dict[str, Any] | None,
    streaming: bool = False,
) -> Any:
    """Inject reasoning metadata into content (backward compatibility wrapper).

    This function is kept for backward compatibility with tests.
    It delegates to ReasoningInjector.
    """
    from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
        ReasoningInjector,
    )

    injector = ReasoningInjector()
    return injector.inject_reasoning(content, metadata or {}, streaming=streaming)


def _normalize_content(content: Any) -> Any:
    """Normalize content for processing (backward compatibility wrapper).

    This function is kept for backward compatibility with tests.
    It delegates to ReasoningInjector's internal normalization.
    """
    from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
        ReasoningInjector,
    )

    injector = ReasoningInjector()
    # Access the private method via the instance
    return injector._normalize_content(content)  # type: ignore[attr-defined]


def _format_chunk_as_sse(content: dict | bytes | str) -> bytes:
    """Format content as SSE bytes (backward compatibility wrapper).

    This function is kept for backward compatibility with tests.
    It delegates to SSEFormatter.format_chunk().

    Args:
        content: Content to format (dict, bytes, or str)

    Returns:
        SSE-formatted bytes
    """
    from src.core.transport.fastapi.adapters.sse.formatter import SSEFormatter

    formatter = SSEFormatter()
    return formatter.format_chunk(content)


def _build_streaming_payload(
    content: Any,
    metadata: dict[str, Any],
    reasoning_text: str | None,
    *,
    streaming: bool = True,
) -> dict[str, Any]:
    """Build OpenAI-style payload when content is not dict (backward compatibility wrapper).

    This function is kept for backward compatibility with tests.
    It delegates to ReasoningInjector.build_streaming_payload().

    Args:
        content: Non-dict content
        metadata: Metadata to include in payload
        reasoning_text: Optional reasoning text (extracted from metadata if None)
        streaming: Whether this is a streaming payload

    Returns:
        OpenAI-style dict payload
    """
    from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
        ReasoningInjector,
    )

    injector = ReasoningInjector()
    # If reasoning_text is provided, add it to metadata
    if reasoning_text and "reasoning_content" not in metadata:
        metadata = {**metadata, "reasoning_content": reasoning_text}
    # Use the public method which handles reasoning_text extraction
    return injector.build_streaming_payload(content, metadata, streaming=streaming)


__all__ = [
    "to_fastapi_response",
    "to_fastapi_streaming_response",
    "domain_response_to_fastapi",
    "_chunk_signals_done",  # Exported for content_converter.py
    "_inject_reasoning_metadata",  # Exported for tests
    "_normalize_content",  # Exported for tests
    "_format_chunk_as_sse",  # Exported for tests
    "_build_streaming_payload",  # Exported for tests
]
