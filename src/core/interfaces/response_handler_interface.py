"""
Response handler interfaces.

This module defines interfaces for handling streaming and non-streaming responses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


class IResponseHandler(ABC):
    """Base interface for response handlers."""

    @abstractmethod
    async def process_response(self, response: Any) -> Any:
        """Process a response.

        Args:
            response: The response to process

        Returns:
            The processed response
        """


class INonStreamingResponseHandler(IResponseHandler):
    """Interface for handling non-streaming responses."""

    @abstractmethod
    async def process_response(self, response: dict[str, Any]) -> ResponseEnvelope:
        """Process a non-streaming response.

        Args:
            response: The non-streaming response to process

        Returns:
            The processed response envelope
        """


class IStreamingResponseHandler(IResponseHandler):
    """Interface for handling streaming responses."""

    @abstractmethod
    async def process_response(
        self, response: AsyncIterator[bytes]
    ) -> StreamingResponseEnvelope:
        """Process a streaming response.

        Args:
            response: The streaming response to process

        Returns:
            The processed streaming response envelope
        """
