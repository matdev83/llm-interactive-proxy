"""
Response handler interfaces.

This module defines interfaces for handling streaming and non-streaming responses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict

from src.core.domain.response_envelope import ResponseEnvelope
from src.core.domain.streaming_response_envelope import StreamingResponseEnvelope


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
        pass


class INonStreamingResponseHandler(IResponseHandler):
    """Interface for handling non-streaming responses."""
    
    @abstractmethod
    async def process_response(self, response: Dict[str, Any]) -> ResponseEnvelope:
        """Process a non-streaming response.
        
        Args:
            response: The non-streaming response to process
            
        Returns:
            The processed response envelope
        """
        pass


class IStreamingResponseHandler(IResponseHandler):
    """Interface for handling streaming responses."""
    
    @abstractmethod
    async def process_response(
        self, 
        response: AsyncIterator[bytes]
    ) -> StreamingResponseEnvelope:
        """Process a streaming response.
        
        Args:
            response: The streaming response to process
            
        Returns:
            The processed streaming response envelope
        """
        pass
