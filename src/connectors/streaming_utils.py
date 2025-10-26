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
        IStreamNormalizer,
    )
else:
    from src.core.interfaces.streaming_response_processor_interface import (
        IStreamNormalizer,
    )


class _PassthroughStreamNormalizer(IStreamNormalizer):
    async def process_stream(
        self, iterator: AsyncIterator[Any], output_format: str = "objects"
    ) -> AsyncGenerator[StreamingContent | bytes, None]:
        # Simple passthrough that converts bytes to StreamingContent or passes through as-is
        if output_format == "bytes":
            # For bytes output, yield items as-is if they're bytes, or convert
            async for item in iterator:
                if isinstance(item, bytes):
                    yield item
                else:
                    yield str(item).encode()
        else:
            # For objects output, create StreamingContent objects
            from src.core.domain.streaming_content import StreamingContent

            async for item in iterator:
                if isinstance(item, bytes):
                    yield StreamingContent(content=item.decode(), is_done=True)
                else:
                    yield StreamingContent(content=str(item), is_done=True)

    def reset(self) -> None:
        return None


def _resolve_stream_normalizer_via_di() -> IStreamNormalizer | None:
    """Resolve configured stream normalizer from the DI container when available."""

    try:
        from src.core.di.services import get_or_build_service_provider
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer,
        )
    except ImportError:
        return None

    try:
        provider = get_or_build_service_provider()
        normalizer = provider.get_service(cast(type, IStreamNormalizer))
    except Exception as exc:  # pragma: no cover - defensive logging
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to resolve IStreamNormalizer from DI: %s", exc, exc_info=True
            )
        return None

    return cast("IStreamNormalizer | None", normalizer)


def _build_fallback_stream_normalizer() -> IStreamNormalizer:
    """Construct a conservative stream normalizer when DI resolution fails."""

    try:
        from src.core.di.services import (
            get_service_collection,
            set_service_provider,
        )
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer,
        )
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("Streaming DI services unavailable") from exc

    services = get_service_collection()
    fallback_provider = services.build_service_provider()

    try:
        set_service_provider(fallback_provider)
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to update global provider while creating fallback normalizer",
                exc_info=True,
            )

    try:
        normalizer = fallback_provider.get_service(cast(type, IStreamNormalizer))
    except Exception:
        normalizer = None

    if normalizer is not None:
        return normalizer

    if logger.isEnabledFor(logging.WARNING):
        logger.warning(
            "Falling back to passthrough stream normalizer; loop detection may be unavailable"
        )

    return _PassthroughStreamNormalizer()


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
            normalizer = _resolve_stream_normalizer_via_di()
            if normalizer is None:
                normalizer = _build_fallback_stream_normalizer()

            reset_method = getattr(normalizer, "reset", None)
            if callable(reset_method):
                try:
                    reset_method()
                except Exception as exc:  # pragma: no cover - defensive logging
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to reset stream normalizer: %s",
                            exc,
                            exc_info=True,
                        )
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
    )
