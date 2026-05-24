"""Interface for stream formatting service.

Responsible for converting domain chunks to SSE-encoded bytes
and validating completion tokens.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class IStreamFormattingService(ABC):
    """Service interface for SSE stream formatting and token validation."""

    @abstractmethod
    def stream_as_sse_bytes(self, stream: AsyncIterator[Any]) -> AsyncIterator[bytes]:
        """Convert domain chunks to SSE-encoded bytes.

        Accepts an async iterator that may yield ProcessedResponse, dict, str, or bytes
        and produces an async iterator of bytes suitable for wire capture and direct
        transport to clients.

        Args:
            stream: Async iterator yielding domain chunks.

        Returns:
            Async iterator yielding SSE-encoded bytes.
        """

    @abstractmethod
    def is_valid_completion_token(self, chunk: Any) -> bool:
        """Check if chunk contains valid completion content.

        A valid completion token is one that:
        - Is not empty or whitespace-only
        - Is not a [DONE] marker
        - Contains actual content (text delta or tool call)

        Args:
            chunk: The chunk to validate.

        Returns:
            True if chunk contains valid completion content.
        """

    @abstractmethod
    def format_chunk_as_sse(self, content: Any) -> bytes:
        """Format a single chunk as SSE bytes.

        Content that already begins with `data:` is passed through unchanged.
        Raw `[DONE]` / `["DONE"]` is normalized to `b"data: [DONE]\\n\\n"`.
        Otherwise returns bytes framed as `data: {payload}\\n\\n`.

        Args:
            content: The content to format (ProcessedResponse, dict, str, or bytes).

        Returns:
            SSE-framed bytes.
        """

    @abstractmethod
    def chunk_signals_done(self, content: Any, metadata: dict[str, Any] | None) -> bool:
        """Check if chunk signals stream completion.

        Detects completion signaled by:
        - Raw/sse `[DONE]` / `["DONE"]`
        - `metadata.finish_reason`
        - `content.metadata.finish_reason`
        - OpenAI-style `choices[*].finish_reason` / empty deltas with finish_reason

        Args:
            content: The chunk content.
            metadata: Optional metadata dictionary.

        Returns:
            True if chunk signals stream completion.
        """
