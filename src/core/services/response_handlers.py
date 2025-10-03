"""
Response handler implementations.

This module provides implementations of the response handler interfaces.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_handler_interface import (
    INonStreamingResponseHandler,
    IStreamingResponseHandler,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


class DefaultNonStreamingResponseHandler(INonStreamingResponseHandler):
    """Default implementation of the non-streaming response handler."""

    async def process_response(self, response: dict[str, Any]) -> ResponseEnvelope:
        """Process a non-streaming response.

        Args:
            response: The non-streaming response to process

        Returns:
            The processed response envelope
        """
        # Create a response envelope with the response content
        return ResponseEnvelope(
            content=response,
            status_code=200,
            headers={"content-type": "application/json"},
        )


class DefaultStreamingResponseHandler(IStreamingResponseHandler):
    """Default implementation of the streaming response handler."""

    async def process_response(
        self, response: AsyncIterator[bytes]
    ) -> StreamingResponseEnvelope:
        """Process a streaming response.

        Args:
            response: The streaming response to process

        Returns:
            The processed streaming response envelope
        """
        # Create a streaming response envelope with the response iterator
        return StreamingResponseEnvelope(
            content=self._normalize_stream(response),
            headers={"content-type": "text/event-stream"},
        )

    async def _normalize_stream(
        self, source: AsyncIterator[bytes]
    ) -> AsyncIterator[ProcessedResponse]:
        """Normalize a streaming response.

        Args:
            source: The source iterator

        Yields:
            Normalized chunks from the source iterator as ProcessedResponse objects
        """
        async for chunk in source:
            yield ProcessedResponse(content=chunk.decode("utf-8"))
