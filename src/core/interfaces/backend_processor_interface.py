"""
Interface for backend processing.

This module defines the interface for processing requests through a backend service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


class IBackendProcessor(ABC):
    """Interface for processing requests through a backend service."""

    @abstractmethod
    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process a request through the backend service.

        Args:
            request: The request to process
            session_id: The session ID
            context: Optional request context

        Returns:
            The response from the backend
        """
