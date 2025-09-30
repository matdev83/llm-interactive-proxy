"""
FastAPI response adapters.

This module contains adapters for converting domain response objects
to FastAPI/Starlette response objects.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi.responses import JSONResponse, Response
from starlette.responses import StreamingResponse

from src.core.domain.chat import ChatResponse, StreamingChatResponse

# Some environments may fail mypy import resolution for local packages; silence here
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


def _format_chunk_as_sse(chunk: Any) -> bytes:
    """Format a chunk as SSE (Server-Sent Events) format.

    This is the critical fix for streaming responses - dict chunks must be
    formatted as `data: {json}\\n\\n` for proper SSE format.

    Args:
        chunk: The chunk to format (dict, str, bytes, or other)

    Returns:
        Formatted chunk as bytes
    """
    if isinstance(chunk, dict):
        # Format as SSE: data: {json}\n\n
        sse_line = f"data: {json.dumps(chunk)}\n\n"
        return sse_line.encode("utf-8")
    elif isinstance(chunk, str):
        return chunk.encode("utf-8")
    elif isinstance(chunk, bytes):
        return chunk
    else:
        return str(chunk).encode("utf-8")


async def _string_to_async_iterator(content: bytes) -> AsyncIterator[ProcessedResponse]:
    """Convert a bytes object to an async iterator that yields the content once."""
    yield ProcessedResponse(content=content.decode("utf-8"))


def to_fastapi_response(
    domain_response: Any, content_converter: Callable[[Any], Any] | None = None
) -> Response:
    """Convert a domain response envelope to a FastAPI response.

    Args:
        domain_response: The domain response envelope
        content_converter: Optional function to convert the content
            before creating the response

    Returns:
        A FastAPI response
    """
    envelope = _normalize_response_envelope(domain_response)
    content = _apply_content_converter(envelope.content, content_converter)
    headers = envelope.headers or {}
    status_code = envelope.status_code
    media_type = getattr(envelope, "media_type", "application/json")

    if media_type == "application/json":
        json_content = _prepare_json_content(content)
        safe_content = _sanitize_json_content(json_content)
        safe_headers = _sanitize_headers(headers)
        safe_status_code = _sanitize_status_code(status_code)
        final_status_code = _handle_backend_error_status_code(
            safe_content, safe_status_code
        )
        return _create_json_response(safe_content, final_status_code, safe_headers)
    else:
        return _create_other_response(content, status_code, headers, media_type)


def _normalize_response_envelope(domain_response: Any) -> ResponseEnvelope:
    if isinstance(domain_response, ResponseEnvelope):
        return domain_response
    elif isinstance(domain_response, ChatResponse):
        return ResponseEnvelope(
            content=domain_response.model_dump(), headers=None, status_code=200
        )
    elif isinstance(domain_response, dict):
        return ResponseEnvelope(content=domain_response, headers=None, status_code=200)
    else:
        return ResponseEnvelope(content=domain_response, headers=None, status_code=200)


def _apply_content_converter(
    content: Any, converter: Callable[[Any], Any] | None
) -> Any:
    if converter:
        return converter(content)
    return content


def _prepare_json_content(content: Any) -> Any:
    if hasattr(content, "model_dump"):
        return content.model_dump()
    elif is_dataclass(content) and not isinstance(content, type):
        return asdict(content)
    return content


def _sanitize_json_content(obj: Any) -> Any:
    try:
        import asyncio

        try:
            from unittest.mock import AsyncMock

            async_mock = AsyncMock
        except ImportError:
            async_mock = None
    except ImportError:
        async_mock = None

    def _sanitize(o: Any) -> Any:
        if o is None:
            return None
        if isinstance(o, dict):
            return {k: _sanitize(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_sanitize(v) for v in o]
        if isinstance(o, tuple):
            return tuple(_sanitize(v) for v in o)
        try:
            if asyncio.iscoroutine(o):
                return str(o)
        except TypeError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Sanitize: Could not check for coroutine: %s", o)
        if async_mock is not None:
            try:
                if isinstance(o, async_mock):
                    return str(o)
            except TypeError:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Sanitize: Could not check for async_mock: %s", o)
        try:
            json.dumps(o)
            return o
        except TypeError:
            return str(o)

    return _sanitize(obj)


def _sanitize_headers(headers: Any) -> dict[str, Any]:
    safe_headers = {}
    if headers is not None:
        if hasattr(headers, "items") and not callable(headers):
            try:
                safe_headers = dict(headers)
            except (TypeError, ValueError):
                safe_headers = {}
        elif hasattr(headers, "_mock_name") or hasattr(headers, "_execute_mock_call"):
            safe_headers = {}
    return safe_headers


def _sanitize_status_code(status_code: Any) -> int:
    safe_status_code = 200
    if status_code is not None:
        if hasattr(status_code, "_mock_name") or hasattr(
            status_code, "_execute_mock_call"
        ):
            safe_status_code = 200
        else:
            try:
                safe_status_code = int(status_code)
            except (TypeError, ValueError):
                safe_status_code = 200
    return safe_status_code


def _handle_backend_error_status_code(content: Any, status_code: int) -> int:
    # Preserve original status code; specific error mappings are handled upstream
    return status_code


def _create_json_response(
    content: Any, status_code: int, headers: dict[str, Any]
) -> JSONResponse:
    return JSONResponse(content=content, status_code=status_code, headers=headers)


def _create_other_response(
    content: Any, status_code: int, headers: dict[str, Any], media_type: str
) -> Response:
    content_str = content
    if isinstance(content, dict | list | tuple):
        try:
            content_str = json.dumps(content)
        except (TypeError, ValueError):
            content_str = str(content)

    return Response(
        content=content_str,
        status_code=status_code,
        headers=headers,
        media_type=media_type,
    )


def to_fastapi_streaming_response(
    domain_response: StreamingResponseEnvelope,
) -> StreamingResponse:
    """Convert a domain streaming response envelope to a FastAPI streaming response.

    Args:
        domain_response: The domain streaming response envelope

    Returns:
        A FastAPI streaming response
    """

    # Ensure the async iterator yields bytes (some backends yield str)
    async def _byte_streamer(
        it: AsyncIterator[Any] | Iterable[Any],
    ) -> AsyncIterator[bytes]:
        try:
            async for chunk in it:  # type: ignore
                yield _format_chunk_as_sse(chunk)
        except TypeError:
            # Not an async iterator; handle as sync iterable
            for chunk in it:  # type: ignore
                yield _format_chunk_as_sse(chunk)

    content_iter = domain_response.content
    return StreamingResponse(
        content=_byte_streamer(content_iter),
        media_type=getattr(domain_response, "media_type", "text/event-stream"),
        headers=domain_response.headers or {},
    )


def domain_response_to_fastapi(
    domain_response: Any, content_converter: Callable[[Any], Any] | None = None
) -> Response | StreamingResponse:
    """Convert any domain response to a FastAPI response.

    This function detects the type of domain response and calls the appropriate
    adapter function.

    Args:
        domain_response: The domain response envelope (streaming or non-streaming)
        content_converter: Optional function to convert the content for non-streaming
            responses before creating the response

    Returns:
        A FastAPI response (streaming or non-streaming)
    """
    # Detect streaming envelope by type name or class
    if (
        isinstance(domain_response, StreamingResponseEnvelope)
        or domain_response.__class__.__name__ == "StreamingResponseEnvelope"
    ):
        return to_fastapi_streaming_response(domain_response)

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
            )
        )

    return to_fastapi_response(domain_response, content_converter)
