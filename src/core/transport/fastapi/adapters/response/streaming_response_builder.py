"""Streaming response builder for response adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.transport.fastapi.adapters.protocols import (
    ISSEFormatter,
)
from src.core.transport.fastapi.adapters.sse.formatter import SSEFormatter


class StreamingResponseBuilder:
    """Build FastAPI StreamingResponse from StreamingResponseEnvelope.

    Creates streaming responses with text/event-stream media type.
    Note: Actual stream conversion is handled in Phase 4 (StreamingContentConverter).
    """

    def __init__(self, sse_formatter: ISSEFormatter | None = None) -> None:
        """Initialize streaming response builder.

        Args:
            sse_formatter: Optional SSE formatter. Creates default if not provided.
        """
        self._sse_formatter = sse_formatter or SSEFormatter()

    def build(self, envelope: StreamingResponseEnvelope) -> StreamingResponse:
        """Build StreamingResponse from envelope.

        Args:
            envelope: Streaming response envelope

        Returns:
            FastAPI StreamingResponse
        """
        # Handle null content with empty iterator
        envelope_content = envelope.content
        if envelope_content is None:

            async def empty_gen() -> AsyncIterator[bytes]:
                # Empty async generator - the return statement with the iterator
                # return type annotation makes this a valid async generator
                return
                # The yield is unreachable but required for type inference
                yield b""  # pragma: no cover

            content: AsyncIterator[bytes] = empty_gen()
        else:
            # Ensure content is an async iterator of bytes
            if isinstance(envelope_content, AsyncIterator):
                # Already an async iterator - assume it yields bytes
                content = envelope_content  # type: ignore[assignment]
            else:
                # If it's a regular iterator or iterable, convert it
                async def convert_gen() -> AsyncIterator[bytes]:
                    for item in envelope_content:  # type: ignore[union-attr]
                        if isinstance(item, bytes):
                            yield item
                        elif isinstance(item, str):
                            yield item.encode("utf-8")
                        else:
                            yield str(item).encode("utf-8")

                content = convert_gen()

        # Create streaming response with text/event-stream media type
        return StreamingResponse(
            content=content,
            status_code=envelope.status_code or 200,
            media_type="text/event-stream",
            headers=envelope.headers or {},
        )
