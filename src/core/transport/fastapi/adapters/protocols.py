"""Protocol definitions for response adapter layers.

This module defines all protocol interfaces (contracts) for the response adapter
subsystem using Python Protocol classes for structural subtyping.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from starlette.responses import JSONResponse, Response, StreamingResponse

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.streaming.streaming_content import StreamingContent

# SSE Layer Protocols


class ISSEFormatter(Protocol):
    """Format content as SSE bytes."""

    def format_chunk(self, content: dict | bytes | str) -> bytes:
        """Format a single chunk as SSE bytes.

        Args:
            content: Content to format (dict, bytes, or str)

        Returns:
            SSE-formatted bytes
        """
        ...


class ISSEDecoder(Protocol):
    """Decode SSE payloads."""

    def decode_payload(self, payload: bytes | str) -> tuple[Any, dict[str, Any], bool]:
        """Decode SSE payload.

        Args:
            payload: SSE-formatted payload (bytes or str)

        Returns:
            Tuple of (decoded_content, metadata_hints, is_done)
        """
        ...


# Metadata Layer Protocols


class IReasoningInjector(Protocol):
    """Inject reasoning metadata into payloads."""

    def inject_reasoning(
        self,
        content: Any,
        metadata: dict[str, Any],
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
        self, content: Any, metadata: dict[str, Any]
    ) -> dict[str, Any]:
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

    def normalize(self, usage: dict[str, Any] | None) -> dict[str, int]:
        """Normalize usage to standard format.

        Args:
            usage: Usage dictionary or None

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
        self, headers: dict[str, str], usage: dict[str, Any]
    ) -> dict[str, str]:
        """Add usage headers to response headers.

        Args:
            headers: Existing headers dictionary
            usage: Usage dictionary

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
        self, raw_stream: AsyncIterator[Any], context: dict[str, Any]
    ) -> AsyncIterator[StreamingContent]:
        """Convert raw chunks to StreamingContent.

        Args:
            raw_stream: Raw stream iterator
            context: Conversion context

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
