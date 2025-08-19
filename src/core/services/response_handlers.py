"""
Response handler implementations.

This module provides implementations of the response handler interfaces.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict

from src.core.domain.response_envelope import ResponseEnvelope
from src.core.domain.streaming_response_envelope import StreamingResponseEnvelope
from src.core.interfaces.response_handler_interface import (
    INonStreamingResponseHandler,
    IStreamingResponseHandler,
)

logger = logging.getLogger(__name__)


class DefaultNonStreamingResponseHandler(INonStreamingResponseHandler):
    """Default implementation of the non-streaming response handler."""
    
    async def process_response(self, response: Dict[str, Any]) -> ResponseEnvelope:
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
        self, 
        response: AsyncIterator[bytes]
    ) -> StreamingResponseEnvelope:
        """Process a streaming response.
        
        Args:
            response: The streaming response to process
            
        Returns:
            The processed streaming response envelope
        """
        # Create a streaming response envelope with the response iterator
        return StreamingResponseEnvelope(
            iterator_supplier=lambda: self._normalize_stream(response),
            headers={"content-type": "text/event-stream"},
        )
    
    async def _normalize_stream(self, source: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        """Normalize a streaming response.
        
        Args:
            source: The source iterator
            
        Yields:
            Normalized chunks from the source iterator
        """
        async for chunk in source:
            # Check if the chunk is a valid JSON object
            try:
                # Try to parse the chunk as JSON
                json_data = json.loads(chunk.decode("utf-8"))
                
                # If it's a valid JSON object, yield it as is
                yield chunk
            except json.JSONDecodeError:
                # If it's not a valid JSON object, normalize it
                # This could involve wrapping it in a JSON object or other processing
                # For now, just yield it as is
                yield chunk
