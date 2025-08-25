"""
Streaming response processor interface.

This module defines the interface for streaming response processor components.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from src.core.interfaces.response_processor_interface import ProcessedResponse


class IStreamingResponseProcessor(ABC):
    """Interface for streaming response processor components."""

    @abstractmethod
    def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming response.

        Args:
            response_iterator: An async iterator of response chunks
            session_id: The session ID associated with this request

        Yields:
            Processed response chunks
        """
