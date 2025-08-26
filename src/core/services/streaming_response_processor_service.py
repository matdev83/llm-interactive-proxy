"""
Streaming response processor service implementation.

This module provides the implementation of the streaming response processor interface.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.interfaces.streaming_response_processor_interface import (
    IStreamingResponseProcessor,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer

logger = logging.getLogger(__name__)


class StreamingResponseProcessorService(IStreamingResponseProcessor):
    """Service for processing streaming responses."""

    def __init__(
        self,
        stream_normalizer: StreamNormalizer | None = None,
        middleware: list[IResponseMiddleware] | None = None,
    ) -> None:
        """Initialize the streaming response processor service.

        Args:
            stream_normalizer: The stream normalizer to use for processing streams
            middleware: Optional list of middleware to apply to responses
        """
        self._stream_normalizer = stream_normalizer or StreamNormalizer()
        self._middleware = middleware or []

    async def register_middleware(self, middleware: IResponseMiddleware) -> None:
        """Register a middleware component to process responses.

        Args:
            middleware: The middleware component to register
        """
        self._middleware.append(middleware)

    async def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:  # type: ignore
        """Process a streaming response.

        Args:
            response_iterator: An async iterator of response chunks
            session_id: The session ID associated with this request

        Yields:
            Processed response chunks
        """
        # Create a normalized stream from the raw response iterator, ensuring objects are returned
        normalized_stream = self._stream_normalizer.process_stream(
            response_iterator, output_format="objects"
        )

        # Process each normalized chunk
        async for content in normalized_stream:
            # Convert StreamingContent to ProcessedResponse
            processed_response = ProcessedResponse(
                content=content.content,  # type: ignore
                metadata=content.metadata,  # type: ignore
                usage=content.usage,  # type: ignore
            )

            # Apply middleware
            context = {"session_id": session_id, "response_type": "stream"}
            for middleware in self._middleware:
                processed_response = await middleware.process(
                    processed_response, session_id, context
                )

            yield processed_response
