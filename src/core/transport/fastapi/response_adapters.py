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

logger = logging.getLogger(__name__)


async def _string_to_async_iterator(content: bytes) -> AsyncIterator[bytes]:
    """Convert a bytes object to an async iterator that yields the content once."""
    yield content


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
    # Normalize different domain-level response shapes into ResponseEnvelope
    if isinstance(domain_response, ResponseEnvelope):
        envelope = domain_response
    elif isinstance(domain_response, ChatResponse):
        # Convert ChatResponse (pydantic) to legacy dict
        envelope = ResponseEnvelope(
            content=domain_response.model_dump(), headers=None, status_code=200
        )
    elif isinstance(domain_response, dict):
        envelope = ResponseEnvelope(
            content=domain_response, headers=None, status_code=200
        )
    elif isinstance(domain_response, tuple) and len(domain_response) == 2:
        # (content, headers) tuple
        envelope = ResponseEnvelope(
            content=domain_response[0], headers=domain_response[1], status_code=200
        )
    else:
        # Fallback: wrap whatever we got
        envelope = ResponseEnvelope(
            content=domain_response, headers=None, status_code=200
        )

    # Extract data from the envelope
    content = envelope.content
    headers = envelope.headers or {}
    status_code = envelope.status_code
    media_type = getattr(envelope, "media_type", "application/json")

    # Apply content converter if provided
    if content_converter:
        content = content_converter(content)

    # Create the appropriate response based on media type
    if media_type == "application/json":
        # Ensure content is a dictionary for JSONResponse
        if hasattr(content, "model_dump"):
            content = content.model_dump()
        elif is_dataclass(content) and not isinstance(content, type):
            content = asdict(content)

        # Sanitize content to avoid un-awaited coroutine/AsyncMock objects
        try:
            import asyncio

            # Try to import AsyncMock for detection
            try:
                from unittest.mock import AsyncMock

                async_mock = AsyncMock
            except ImportError:
                async_mock = None
        except Exception:
            async_mock = None

        def _sanitize(obj: Any) -> Any:
            if obj is None:
                return None
            if isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize(v) for v in obj]
            if isinstance(obj, tuple):
                return tuple(_sanitize(v) for v in obj)
            # Coroutine objects
            try:
                if asyncio.iscoroutine(obj):
                    return str(obj)
            except Exception:
                pass
            if async_mock is not None:
                try:
                    if isinstance(obj, async_mock):
                        return str(obj)
                except TypeError:
                    # async_mock might not be a valid type for isinstance
                    pass
            # Fallback for objects not directly serializable
            try:
                json.dumps(obj)
                return obj
            except Exception:
                return str(obj)

        safe_content = _sanitize(content)
        return JSONResponse(
            content=safe_content,
            status_code=status_code,
            headers=headers,
        )
    else:
        # For other media types, convert content to string if needed
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
                if isinstance(chunk, str):
                    yield chunk.encode("utf-8")
                elif isinstance(chunk, bytes):
                    yield chunk
                else:
                    yield str(chunk).encode("utf-8")
        except TypeError:
            # Not an async iterator; handle as sync iterable
            for chunk in it:  # type: ignore
                if isinstance(chunk, str):
                    yield chunk.encode("utf-8")
                elif isinstance(chunk, bytes):
                    yield chunk
                else:
                    yield str(chunk).encode("utf-8")

    content_iter = domain_response.content
    return StreamingResponse(
        content=_byte_streamer(content_iter),
        media_type=getattr(domain_response, "media_type", "text/event-stream"),
        headers=domain_response.headers or {},
    )


def domain_response_to_fastapi(
    domain_response: Any,
    content_converter: Callable[[Any], Any] | None = None,
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
                content=content_iterator,
                media_type="text/event-stream",
                headers={},
            )
        )

    return to_fastapi_response(domain_response, content_converter)
