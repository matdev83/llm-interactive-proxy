from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import TypeAlias

from src.core.domain.streaming_response_processor import (
    StreamingContent,
)

# Type alias for raw stream items - can be StreamingContent, bytes, dicts, or other formats
# This is intentionally broad to accommodate various input formats before normalization
StreamItem: TypeAlias = object

# Type alias for cancel callback - a callable that takes no arguments and returns None
CancelCallback: TypeAlias = Callable[[], None]


class IStreamNormalizer(ABC):
    """Interface for normalizing streaming responses."""

    @abstractmethod
    def process_stream(
        self,
        stream: AsyncIterator[StreamItem],
        output_format: str = "bytes",
        cancel_callback: CancelCallback | None = None,
    ) -> AsyncGenerator[StreamingContent | bytes, None]:
        """Process a stream and convert to the desired output format.

        Args:
            stream: The input stream to process (can contain StreamingContent, bytes, dicts, etc.)
            output_format: The desired output format ("bytes" or "objects")
            cancel_callback: Optional callback to cancel upstream streaming

        Returns:
            An async iterator of the processed stream in the requested format
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset any processor state before handling a new stream."""
