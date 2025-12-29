"""
Utilities for handling streaming responses from backends.

This module provides helper functions to normalize and process
streaming responses from different backends into consistent formats.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import TYPE_CHECKING, Any, cast

from src.core.domain.responses import StreamingResponseEnvelope

logger = logging.getLogger(__name__)


if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.core.domain.streaming_response_processor import StreamingContent
    from src.core.interfaces.streaming_response_processor_interface import (
        IStreamNormalizer as IProcessingStreamNormalizer,
    )
else:
    from src.core.interfaces.streaming_response_processor_interface import (
        IStreamNormalizer as IProcessingStreamNormalizer,
    )


class _PassthroughStreamNormalizer(IProcessingStreamNormalizer):
    async def process_stream(
        self,
        stream: AsyncIterator[Any],
        output_format: str = "objects",
        cancel_callback: Any | None = None,
    ) -> AsyncGenerator[StreamingContent | bytes, None]:
        # Simple passthrough that converts bytes to StreamingContent or passes through as-is
        if output_format == "bytes":
            # For bytes output, yield items as-is if they're bytes, or convert
            async for item in stream:
                if isinstance(item, bytes):
                    yield item
                else:
                    yield str(item).encode()
        else:
            # For objects output, create StreamingContent objects
            from src.core.domain.streaming_content import StreamingContent

            async for item in stream:
                # If item is already StreamingContent, use it directly
                # Otherwise, convert using from_raw (which handles transport-neutral formats only)
                # Note: This is a fallback path - provider-specific formats should be
                # normalized by provider normalizers before reaching here
                if isinstance(item, StreamingContent):
                    yield item
                else:
                    try:
                        yield StreamingContent.from_raw(item)
                    except (ValueError, TypeError, KeyError) as err:
                        logger.debug(
                            "Failed to convert item to StreamingContent, using fallback: %s, error: %s",
                            type(item).__name__,
                            err,
                            exc_info=True,
                        )
                        content = (
                            item.decode() if isinstance(item, bytes) else str(item)
                        )
                        yield StreamingContent(content=content)

    def reset(self) -> None:
        return None


def _resolve_stream_normalizer_via_di() -> IProcessingStreamNormalizer | None:
    """Resolve configured stream normalizer from the DI container when available."""

    try:
        from src.core.di.services import get_or_build_service_provider
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer as IProcessingStreamNormalizer,
        )
    except ImportError:
        return None

    try:
        provider = get_or_build_service_provider()
        normalizer = provider.get_service(cast(type, IProcessingStreamNormalizer))
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug(
            "Failed to resolve IProcessingStreamNormalizer from DI: %s",
            exc,
            exc_info=True,
        )
        return None

    return cast("IProcessingStreamNormalizer | None", normalizer)


# Removed _build_fallback_stream_normalizer() - fallback construction violates requirement 5.2
# All normalizers must be provided via explicit DI wiring


def _encode_chunk_to_bytes(chunk: Any) -> bytes:
    """Encode a chunk to bytes efficiently.

    Args:
        chunk: The chunk to encode (str, bytes, or object)

    Returns:
        The chunk encoded as bytes
    """
    if isinstance(chunk, str):
        return chunk.encode("utf-8")
    elif isinstance(chunk, bytes):
        return chunk
    else:
        try:
            return json.dumps(chunk).encode("utf-8")
        except (TypeError, ValueError):
            return str(chunk).encode("utf-8")


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
            yield _encode_chunk_to_bytes(chunk)
        return

    if hasattr(it, "__iter__"):
        for chunk in it:  # type: ignore[misc]
            yield _encode_chunk_to_bytes(chunk)
        return

    if asyncio.iscoroutine(it):
        res = await it  # type: ignore[arg-type]
        if hasattr(res, "__aiter__"):
            async for chunk in res:  # type: ignore[misc]
                yield _encode_chunk_to_bytes(chunk)
            return
        if hasattr(res, "__iter__"):
            for chunk in res:  # type: ignore[misc]
                yield _encode_chunk_to_bytes(chunk)
            return

    # Fallback: empty
    return


def normalize_streaming_response(
    iterator: AsyncIterator[Any],
    normalize: bool = True,
    media_type: str = "text/event-stream",
    headers: dict[str, str] | None = None,
    cancel_callback: Any | None = None,
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
            normalizer = _resolve_stream_normalizer_via_di()
            if normalizer is None:
                raise RuntimeError(
                    "Stream normalizer is required but not available via DI. "
                    "Ensure streaming services are registered in the DI container."
                )

            reset_method = getattr(normalizer, "reset", None)
            if callable(reset_method):
                try:
                    reset_method()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.debug(
                        "Failed to reset stream normalizer: %s",
                        exc,
                        exc_info=True,
                    )
            try:
                processed_stream = normalizer.process_stream(
                    iterator, output_format="objects", cancel_callback=cancel_callback
                )
            except TypeError:
                # Backward compatibility with normalizers that don't accept cancel_callback
                processed_stream = normalizer.process_stream(
                    iterator, output_format="objects"
                )
            async for chunk in processed_stream:
                if isinstance(chunk, bytes):
                    yield chunk
                elif hasattr(chunk, "to_bytes") and callable(
                    getattr(chunk, "to_bytes", None)
                ):
                    try:
                        yield chunk.to_bytes()  # type: ignore[attr-defined]
                    except (AttributeError, TypeError, ValueError) as err:
                        logger.debug(
                            "Failed to convert chunk with to_bytes(), using str fallback: %s, error: %s",
                            type(chunk).__name__,
                            err,
                            exc_info=True,
                        )
                        yield str(chunk).encode("utf-8")
                else:
                    yield str(chunk).encode("utf-8")
        else:
            # Just ensure we have bytes output
            try:
                async for chunk in _ensure_async_iterator(iterator):
                    # _ensure_async_iterator guarantees bytes
                    yield chunk
            except Exception as e:
                logger.error(
                    f"Error in non-normalized streaming path: {e}", exc_info=True
                )
                # Fallback to empty response with error message
                yield f'data: {{"error": "Streaming error: {e!s}"}}\\n\\n'.encode()
                yield b"data: [DONE]\n\n"

    from typing import cast

    return StreamingResponseEnvelope(
        content=cast(AsyncIterator, create_normalized_stream()),
        media_type=media_type,
        headers=headers or {},
        cancel_callback=cancel_callback,
    )
