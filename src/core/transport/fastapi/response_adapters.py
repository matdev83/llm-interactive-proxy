"""
FastAPI response adapters.

This module contains adapters for converting domain response objects
to FastAPI/Starlette response objects.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, Dict, Optional, Union

from fastapi.responses import JSONResponse, Response
from starlette.responses import StreamingResponse

from src.core.domain.response_envelope import ResponseEnvelope
from src.core.domain.streaming_response_envelope import StreamingResponseEnvelope

logger = logging.getLogger(__name__)


def to_fastapi_response(
    domain_response: ResponseEnvelope, 
    content_converter: Optional[callable] = None
) -> Response:
    """Convert a domain response envelope to a FastAPI response.
    
    Args:
        domain_response: The domain response envelope
        content_converter: Optional function to convert the content
            before creating the response
            
    Returns:
        A FastAPI response
    """
    # Extract data from the envelope
    content = domain_response.content
    headers = domain_response.headers or {}
    status_code = domain_response.status_code
    media_type = domain_response.media_type
    
    # Apply content converter if provided
    if content_converter:
        content = content_converter(content)
    
    # Create the appropriate response based on media type
    if media_type == "application/json":
        return JSONResponse(
            content=content,
            status_code=status_code,
            headers=headers,
        )
    else:
        # For other media types, convert content to string if needed
        if isinstance(content, (dict, list, tuple)):
            try:
                content = json.dumps(content)
            except (TypeError, ValueError):
                content = str(content)
        
        return Response(
            content=content,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
        )


def to_fastapi_streaming_response(
    domain_response: StreamingResponseEnvelope
) -> StreamingResponse:
    """Convert a domain streaming response envelope to a FastAPI streaming response.
    
    Args:
        domain_response: The domain streaming response envelope
            
    Returns:
        A FastAPI streaming response
    """
    return StreamingResponse(
        content=domain_response.content,
        media_type=domain_response.media_type,
        headers=domain_response.headers or {},
    )


def domain_response_to_fastapi(
    domain_response: Union[ResponseEnvelope, StreamingResponseEnvelope],
    content_converter: Optional[callable] = None,
) -> Union[Response, StreamingResponse]:
    """Convert any domain response to a FastAPI response.
    
    This function detects the type of domain response and calls the appropriate
    adapter function.
    
    Args:
        domain_response: The domain response envelope (streaming or non-streaming)
        content_converter: Optional function to convert the content for non-streaming
            responses before creating the response
            
    Returns:
        A FastAPI response (streaming or non-streaming)
    """
    if isinstance(domain_response, StreamingResponseEnvelope):
        return to_fastapi_streaming_response(domain_response)
    else:
        return to_fastapi_response(domain_response, content_converter)
