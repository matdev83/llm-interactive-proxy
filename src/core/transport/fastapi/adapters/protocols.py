"""Protocol definitions for response adapter layers.

This module defines all protocol interfaces (contracts) for the response adapter
subsystem using Python Protocol classes for structural subtyping.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol

from pydantic.types import JsonValue

if TYPE_CHECKING:
    from src.core.domain.openrouter_usage import OpenRouterUsage
    from src.core.domain.request_context import RequestContext
    from src.core.transport.fastapi.adapters.sse.models import DecodedSSE


from starlette.responses import JSONResponse, Response, StreamingResponse

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.interfaces.response_processor_interface import ProcessedResponse

# SSE Layer Protocols


class ISSEFormatter(Protocol):
    """Format content as SSE bytes."""

    def format_chunk(self, content: dict[str, JsonValue] | bytes | str) -> bytes:
        """Format a single chunk as SSE bytes.

        Args:
            content: Content to format (dict, bytes, or str)

        Returns:
            SSE-formatted bytes
        """
        ...


class ISSEDecoder(Protocol):
    """Decode SSE payloads."""

    def decode_payload(self, payload: bytes | str) -> DecodedSSE:
        """Decode SSE payload.

        Args:
            payload: SSE-formatted payload (bytes or str)

        Returns:
            DecodedSSE containing content, metadata, and is_done flag
        """
        ...


# Metadata Layer Protocols


class IReasoningInjector(Protocol):
    """Inject reasoning metadata into payloads."""

    def inject_reasoning(
        self,
        content: Any,
        metadata: dict[str, JsonValue],
        *,
        streaming: bool | None = None,
    ) -> Any:
        """Inject reasoning fields into content.

        Args:
            content: Content to inject into
            metadata: Metadata containing reasoning fields
            streaming: Optional streaming flag. If None, inferred from content.

        Returns:
            Content with reasoning injected
        """
        ...

    def build_streaming_payload(
        self, content: Any, metadata: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        """Build OpenAI-style payload when content is not dict.

        Args:
            content: Non-dict content
            metadata: Metadata to include in payload

        Returns:
            OpenAI-style dict payload
        """
        ...


# Usage Layer Protocols


class IUsageNormalizer(Protocol):
    """Normalize usage dictionaries."""

    def normalize(
        self, usage: dict[str, Any] | OpenRouterUsage | None
    ) -> dict[str, int]:
        """Normalize usage to standard format.

        Args:
            usage: Usage dictionary, OpenRouterUsage instance, or None

        Returns:
            Normalized usage with standard fields as integers
        """
        ...

    def merge_streaming_usage(
        self, existing: dict[str, int], new: dict[str, Any]
    ) -> dict[str, int]:
        """Merge usage keeping highest values.

        Args:
            existing: Existing usage dictionary
            new: New usage dictionary to merge

        Returns:
            Merged usage dictionary with highest values
        """
        ...


class IUsageHeaderInjector(Protocol):
    """Apply usage data as HTTP headers."""

    def inject_headers(
        self,
        headers: dict[str, str],
        usage: dict[str, JsonValue],
        canonical_usage: Any | None = None,
    ) -> dict[str, str]:
        """Add usage headers to response headers.

        Args:
            headers: Existing headers dictionary
            usage: Usage dictionary (fallback when canonical_usage is not available)
            canonical_usage: Optional canonical usage record (takes priority)

        Returns:
            Headers dictionary with usage headers added
        """
        ...


# Sanitization Layer Protocols


class IJSONSanitizer(Protocol):
    """Ensure JSON-safe content."""

    def sanitize(self, content: Any) -> Any:
        """Convert non-serializable objects to safe representations.

        Args:
            content: Content to sanitize

        Returns:
            JSON-safe content
        """
        ...


class IHeaderSanitizer(Protocol):
    """Filter HTTP headers."""

    ALLOWED_PREFIXES: tuple[str, ...]
    """Allowed header name prefixes."""

    HOP_BY_HOP_HEADERS: frozenset[str]
    """Hop-by-hop headers to remove."""

    def sanitize(self, headers: dict[str, str] | None) -> dict[str, str]:
        """Remove disallowed headers.

        Args:
            headers: Headers dictionary or None

        Returns:
            Filtered headers dictionary
        """
        ...


# Capture Layer Protocols


class IWireCaptureCoordinator(Protocol):
    """Coordinate wire capture operations."""

    def schedule_capture(
        self,
        envelope: ResponseEnvelope,
        response_content: Any,
        context: Any | None = None,
    ) -> None:
        """Schedule async capture for non-streaming response.

        Args:
            envelope: Response envelope
            response_content: Response content to capture
            context: Optional request context
        """
        ...

    def wrap_stream(
        self,
        envelope: StreamingResponseEnvelope,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Wrap stream for capture if enabled.

        Args:
            envelope: Streaming response envelope
            stream: Stream iterator to wrap

        Yields:
            Stream chunks (potentially captured)
        """
        ...


# Streaming Layer Protocols


class IToolBlockBuffer(Protocol):
    """Buffer multiline tool blocks."""

    def buffer(self, content: str, stream_id: str | None) -> str:
        """Buffer content, returning complete blocks only.

        Args:
            content: Content to buffer
            stream_id: Optional stream identifier

        Returns:
            Complete tool blocks (empty string if none complete)
        """
        ...

    def flush(self, stream_id: str | None) -> str:
        """Flush any pending content.

        Args:
            stream_id: Optional stream identifier

        Returns:
            All pending buffered content
        """
        ...

    def reset(self, stream_id: str | None) -> None:
        """Reset buffer state.

        Args:
            stream_id: Optional stream identifier
        """
        ...


class IStreamingContentConverter(Protocol):
    """Convert raw stream chunks to StreamingContent."""

    async def convert_stream(
        self,
        raw_stream: AsyncIterator[ProcessedResponse],
        context: dict[str, JsonValue | RequestContext | None],
    ) -> AsyncIterator[StreamingContent]:
        """Convert raw chunks to StreamingContent.

        Args:
            raw_stream: Raw stream iterator of ProcessedResponse chunks
            context: Conversion context containing:
                    - envelope_metadata: dict[str, JsonValue] with envelope metadata
                    - context: RequestContext | None for usage recalculation
                    Note: RequestContext is allowed here as it's needed for usage
                    recalculation logic, but envelope_metadata must be JSON-safe.

        Yields:
            StreamingContent chunks
        """
        ...


# Response Builder Protocols


class IJSONResponseBuilder(Protocol):
    """Build FastAPI JSONResponse."""

    def build(self, envelope: ResponseEnvelope) -> JSONResponse:
        """Build JSONResponse from envelope.

        Args:
            envelope: Response envelope

        Returns:
            FastAPI JSONResponse
        """
        ...


class IStreamingResponseBuilder(Protocol):
    """Build FastAPI StreamingResponse."""

    def build(self, envelope: StreamingResponseEnvelope) -> StreamingResponse:
        """Build StreamingResponse from envelope.

        Args:
            envelope: Streaming response envelope

        Returns:
            FastAPI StreamingResponse
        """
        ...


class IOtherResponseBuilder(Protocol):
    """Build non-JSON responses."""

    def build(self, envelope: ResponseEnvelope) -> Response:
        """Build Response from envelope.

        Args:
            envelope: Response envelope

        Returns:
            FastAPI Response
        """
        ...
