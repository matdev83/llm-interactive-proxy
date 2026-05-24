"""
Streaming interfaces and protocols.

This module contains the core interfaces for the streaming pipeline:
- StreamProducer: Protocol for backend connectors
- IProviderStreamNormalizer: Interface for normalizing provider-specific formats
  (re-exported as IStreamNormalizer for backward compatibility)
- IStreamProcessor: Interface for middleware processors
- IStreamAssembler: Interface for converting to client formats

These interfaces define contracts without any vendor/transport dependencies.

Note: IProviderStreamNormalizer is distinct from the services-layer IStreamNormalizer
which handles middleware pipeline normalization. External code should import
IStreamNormalizer from streaming_contracts.py for backward compatibility.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Protocol, TypeAlias

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.streaming.streaming_content import StreamingContent

# Type alias for raw streaming chunks from backends
# Raw chunks are provider-specific and opaque until normalized
# They can be bytes, dicts, strings, or other provider-specific formats
RawChunk: TypeAlias = object


class StreamProducer(Protocol):
    """Protocol that all streaming backends must implement.

    This protocol defines the contract for backend connectors that produce
    streaming responses.
    """

    async def stream_completion(
        self, request: CanonicalChatRequest
    ) -> AsyncIterator[RawChunk]:
        """Yield raw streaming chunks from the backend.

        Args:
            request: The chat completion request

        Yields:
            Raw streaming chunks from the backend (opaque provider-specific data)
        """
        ...

    def get_provider_name(self) -> str:
        """Return the provider name for logging/metrics.

        Returns:
            Provider name (e.g., "openai", "anthropic", "gemini")
        """
        ...


class IProviderStreamNormalizer(ABC):
    """Interface for normalizing provider-specific streaming responses.

    Provider normalizers convert provider-specific streaming formats into the
    unified StreamingContent representation. This interface is distinct from
    the services-layer IStreamNormalizer which handles middleware pipeline
    normalization.

    Note: This interface is re-exported as IStreamNormalizer from
    streaming_contracts.py for backward compatibility.
    """

    @abstractmethod
    def normalize_stream(
        self, stream: AsyncIterator[RawChunk], provider: str
    ) -> AsyncIterator[StreamingContent]:
        """Convert provider-specific stream to StreamingContent.

        Args:
            stream: Raw stream from backend (opaque provider-specific data)
            provider: Provider name for context

        Yields:
            Normalized StreamingContent chunks
        """
        ...

    @abstractmethod
    def validate_chunk(self, chunk: StreamingContent) -> bool:
        """Validate chunk structure and metadata.

        Args:
            chunk: The chunk to validate

        Returns:
            True if valid, False otherwise
        """
        ...


class IStreamProcessor(ABC):
    """Interface for middleware that processes streaming content.

    Processors can observe or transform streaming content as it flows
    through the pipeline.
    """

    @abstractmethod
    async def process(self, content: StreamingContent) -> StreamingContent:
        """Transform or observe streaming content.

        Args:
            content: The content to process

        Returns:
            The processed content
        """
        ...

    def reset(self) -> None:
        """Reset processor state for new stream.

        This method should be called before processing a new stream to
        ensure clean state isolation.

        Default implementation does nothing. Override if your processor
        maintains state.
        """
        # Default implementation: no state to reset
        return None


class IStreamAssembler(ABC):
    """Interface for converting internal format to client format.

    Assemblers handle the final conversion from StreamingContent to
    client-facing formats like SSE or JSON-lines.
    """

    @abstractmethod
    def assemble_stream(
        self, stream: AsyncIterator[StreamingContent], format: str = "sse"
    ) -> AsyncIterator[bytes]:
        """Convert StreamingContent to client-facing format.

        Args:
            stream: Stream of StreamingContent chunks
            format: Output format ("sse", "json-lines", etc.)

        Yields:
            Formatted bytes ready for client transmission
        """
        ...


# Note: IStreamNormalizer alias is re-exported from streaming_contracts.py for backward compatibility
# External code should import IStreamNormalizer from streaming_contracts.py, not from this module

__all__ = [
    "RawChunk",
    "StreamProducer",
    "IProviderStreamNormalizer",
    "IStreamProcessor",
    "IStreamAssembler",
]
