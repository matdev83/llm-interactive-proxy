"""Streaming response builder for response adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.transport.fastapi.adapters.protocols import (
    ISSEFormatter,
    IUsageHeaderInjector,
)
from src.core.transport.fastapi.adapters.sse.formatter import SSEFormatter
from src.core.transport.fastapi.adapters.usage.header_injector import (
    UsageHeaderInjector,
)


class StreamingResponseBuilder:
    """Build FastAPI StreamingResponse from StreamingResponseEnvelope.

    Creates streaming responses with text/event-stream media type.
    Note: Actual stream conversion is handled in Phase 4 (StreamingContentConverter).
    """

    def __init__(
        self,
        sse_formatter: ISSEFormatter | None = None,
        usage_header_injector: IUsageHeaderInjector | None = None,
    ) -> None:
        """Initialize streaming response builder.

        Args:
            sse_formatter: Optional SSE formatter. Creates default if not provided.
            usage_header_injector: Optional usage header injector. Creates default if not provided.
        """
        self._sse_formatter = sse_formatter or SSEFormatter()
        self._usage_header_injector = usage_header_injector or UsageHeaderInjector()

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
            # Already an async iterator - assume it yields bytes or is handled by body_iterator
            content = envelope_content  # type: ignore[assignment]

        # Inject canonical usage headers if available (Requirement 5.5)
        # Note: StreamingResponseEnvelope doesn't have a usage field, only canonical_usage
        envelope_headers = envelope.headers or {}
        headers = self._usage_header_injector.inject_headers(
            envelope_headers, {}, canonical_usage=envelope.canonical_usage
        )

        # Build streaming headers with defaults
        final_headers = {
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "content-type": "text/event-stream",
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
        }

        # Filter and merge headers (consistent with JSONResponseBuilder)
        # Allow provider-specific headers for usage tracking and rate limiting
        allowed_prefixes = ("x-", "access-control-", "anthropic-", "openai-", "zenmux-")
        for k, v in headers.items():
            if k.lower().startswith(allowed_prefixes):
                final_headers[k] = v

        # Create streaming response with text/event-stream media type
        return StreamingResponse(
            content=content,
            status_code=envelope.status_code or 200,
            media_type="text/event-stream",
            headers=final_headers,
        )
