from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from src.core.domain.streaming_response_processor import (
    StreamingContent,
)
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)


class IStreamNormalizer(ABC):
    """Interface for normalizing streaming responses."""

    @abstractmethod
    async def process_stream(
        self, stream: AsyncIterator[Any], output_format: str = "bytes"
    ) -> AsyncGenerator[StreamingContent | bytes, None]:
        """Process a stream and convert to the desired output format.

        Args:
            stream: The input stream to process
            output_format: The desired output format ("bytes" or "objects")

        Returns:
            An async iterator of the processed stream in the requested format
        """


class IStreamingResponseProcessor(ABC):
    """Interface for processing streaming responses."""

    @abstractmethod
    async def register_middleware(self, middleware: IResponseMiddleware) -> None:
        """Register a middleware component to process responses.

        Args:
            middleware: The middleware component to register
        """

    @abstractmethod
    async def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming response.

        Args:
            response_iterator: An async iterator of response chunks
            session_id: The session ID associated with this request

        Yields:
            Processed response chunks
        """
