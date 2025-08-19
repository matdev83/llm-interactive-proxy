"""
Interface for backend processing.

This module defines the interface for processing requests through a backend service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.response_envelope import ResponseEnvelope
from src.core.domain.streaming_response_envelope import StreamingResponseEnvelope


class IBackendProcessor(ABC):
    """Interface for processing requests through a backend service."""
    
    @abstractmethod
    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: Optional[RequestContext] = None
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process a request through the backend service.
        
        Args:
            request: The request to process
            session_id: The session ID
            context: Optional request context
            
        Returns:
            The response from the backend
        """
        pass
