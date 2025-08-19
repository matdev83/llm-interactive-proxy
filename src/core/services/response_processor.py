"""
Response processor implementation.

This module provides the implementation of the response processor interface.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict

from src.core.domain.response_envelope import ResponseEnvelope
from src.core.domain.streaming_response_envelope import StreamingResponseEnvelope
from src.core.interfaces.response_handler_interface import (
    INonStreamingResponseHandler,
    IStreamingResponseHandler,
)
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.services.response_handlers import (
    DefaultNonStreamingResponseHandler,
    DefaultStreamingResponseHandler,
)

logger = logging.getLogger(__name__)


class ResponseProcessor(IResponseProcessor):
    """Implementation of the response processor interface."""
    
    def __init__(
        self,
        non_streaming_handler: INonStreamingResponseHandler | None = None,
        streaming_handler: IStreamingResponseHandler | None = None,
    ) -> None:
        """Initialize the response processor.
        
        Args:
            non_streaming_handler: Handler for non-streaming responses
            streaming_handler: Handler for streaming responses
        """
        self._non_streaming_handler = non_streaming_handler or DefaultNonStreamingResponseHandler()
        self._streaming_handler = streaming_handler or DefaultStreamingResponseHandler()
    
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
        if is_streaming:
            # Process streaming response
            if isinstance(response, AsyncIterator):
                return await self.process_streaming_response(response)
            else:
                logger.warning(
                    f"Expected AsyncIterator for streaming response, got {type(response)}"
                )
                # Try to convert to a dict and process as non-streaming
                try:
                    return await self.process_non_streaming_response(dict(response))
                except Exception:
                    # If conversion fails, return a simple error response
                    return ResponseEnvelope(
                        content={"error": "Invalid streaming response"},
                        status_code=500,
                    )
        else:
            # Process non-streaming response
            if isinstance(response, dict):
                return await self.process_non_streaming_response(response)
            elif isinstance(response, tuple) and len(response) == 2:
                # Handle tuple of (response, headers)
                response_dict, headers = response
                if isinstance(response_dict, dict):
                    envelope = await self.process_non_streaming_response(response_dict)
                    # Add headers from the tuple
                    envelope.headers.update(headers)
                    return envelope
            
            # If we get here, the response is not in a recognized format
            logger.warning(f"Unexpected response format: {type(response)}")
            return ResponseEnvelope(
                content={"error": "Unexpected response format"},
                status_code=500,
            )
    
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
        return await self._non_streaming_handler.process_response(response)
    
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
        return await self._streaming_handler.process_response(response)