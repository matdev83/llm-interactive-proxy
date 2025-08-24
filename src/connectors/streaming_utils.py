"""
Utilities for handling streaming responses from backends.

This module provides helper functions to normalize and process
streaming responses from different backends into consistent formats.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.streaming_response_processor import StreamNormalizer

logger = logging.getLogger(__name__)


async def _ensure_async_iterator(it: Any) -> AsyncIterator[bytes]:
    """Ensure that a value is an async iterator of bytes.

    Args:
        it: The value to convert to an async iterator

    Returns:
        An async iterator of bytes
    """
    # Normalize different shapes into an async iterator of bytes
    if hasattr(it, "__aiter__"):
        async for chunk in it:  # type: ignore[misc]
            # Ensure bytes output
            if isinstance(chunk, str):
                yield chunk.encode("utf-8")
            elif isinstance(chunk, bytes):
                yield chunk
            else:
                try:
                    yield json.dumps(chunk).encode("utf-8")
                except (TypeError, ValueError):
                    yield str(chunk).encode("utf-8")
        return

    if hasattr(it, "__iter__"):
        for chunk in it:  # type: ignore[misc]
            # Ensure bytes output
            if isinstance(chunk, str):
                yield chunk.encode("utf-8")
            elif isinstance(chunk, bytes):
                yield chunk
            else:
                try:
                    yield json.dumps(chunk).encode("utf-8")
                except (TypeError, ValueError):
                    yield str(chunk).encode("utf-8")
        return

    if asyncio.iscoroutine(it):
        res = await it  # type: ignore[arg-type]
        if hasattr(res, "__aiter__"):
            async for chunk in res:  # type: ignore[misc]
                # Ensure bytes output
                if isinstance(chunk, str):
                    yield chunk.encode("utf-8")
                elif isinstance(chunk, bytes):
                    yield chunk
                else:
                    try:
                        yield json.dumps(chunk).encode("utf-8")
                    except (TypeError, ValueError):
                        yield str(chunk).encode("utf-8")
            return
        if hasattr(res, "__iter__"):
            for chunk in res:  # type: ignore[misc]
                # Ensure bytes output
                if isinstance(chunk, str):
                    yield chunk.encode("utf-8")
                elif isinstance(chunk, bytes):
                    yield chunk
                else:
                    try:
                        yield json.dumps(chunk).encode("utf-8")
                    except (TypeError, ValueError):
                        yield str(chunk).encode("utf-8")
            return

    # Fallback: empty
    return


def normalize_streaming_response(
    iterator: AsyncIterator[Any],
    normalize: bool = True,
    media_type: str = "text/event-stream",
    headers: dict[str, str] | None = None,
) -> StreamingResponseEnvelope:
    """Create a normalized StreamingResponseEnvelope from an async iterator.

    This function ensures a consistent streaming response format across
    different backends by normalizing the stream chunks.

    Args:
        iterator: The raw streaming iterator from a backend
        normalize: Whether to normalize the stream chunks (default: True)
        media_type: The media type of the stream (default: "text/event-stream")
        headers: Optional headers to include in the response

    Returns:
        A StreamingResponseEnvelope containing the normalized stream
    """

    async def create_normalized_stream() -> AsyncIterator[bytes]:
        if normalize:
            # Use StreamNormalizer to get a consistent format
            normalizer = StreamNormalizer()
            processed_stream = normalizer.process_stream(
                iterator, output_format="bytes"
            )
            async for chunk in processed_stream:
                # StreamNormalizer with output_format="bytes" should already yield bytes
                if isinstance(chunk, bytes):
                    yield chunk
                else:
                    # Fallback: convert to bytes conservatively
                    yield str(chunk).encode("utf-8")
        else:
            # Just ensure we have bytes output
            try:
                async for chunk in _ensure_async_iterator(iterator):
                    # _ensure_async_iterator guarantees bytes
                    yield chunk
            except Exception as e:
                logger.error(f"Error in non-normalized streaming path: {e}")
                # Fallback to empty response with error message
                yield f'data: {{"error": "Streaming error: {e!s}"}}\\n\\n'.encode()
                yield b"data: [DONE]\n\n"

    return StreamingResponseEnvelope(
        content=create_normalized_stream(), media_type=media_type, headers=headers or {}
    )
