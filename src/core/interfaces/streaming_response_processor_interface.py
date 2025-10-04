from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from src.core.domain.streaming_response_processor import (
    StreamingContent,
)


class IStreamNormalizer(ABC):
    """Interface for normalizing streaming responses."""

    @abstractmethod
    def process_stream(
        self, stream: AsyncIterator[Any], output_format: str = "bytes"
    ) -> AsyncGenerator[StreamingContent | bytes, None]:
        """Process a stream and convert to the desired output format.

        Args:
            stream: The input stream to process
            output_format: The desired output format ("bytes" or "objects")

        Returns:
            An async iterator of the processed stream in the requested format
        """


