"""
Response processor interface.

This module defines the interface for processing responses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict

from src.core.domain.response_envelope import ResponseEnvelope
from src.core.domain.streaming_response_envelope import StreamingResponseEnvelope


class IResponseProcessor(ABC):
    """Interface for processing responses."""
    
    @abstractmethod
    async def process_response(
        self, 
        response: Any, 
        is_streaming: bool = False
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process a response.
        
        Args:
            response: The response to process
            is_streaming: Whether the response is streaming
            
        Returns:
            The processed response envelope
        """
        pass
        
    @abstractmethod
    async def process_non_streaming_response(
        self, 
        response: Dict[str, Any]
    ) -> ResponseEnvelope:
        """Process a non-streaming response.
        
        Args:
            response: The non-streaming response to process
            
        Returns:
            The processed response envelope
        """
        pass
        
    @abstractmethod
    async def process_streaming_response(
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