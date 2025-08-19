"""
FastAPI request adapters.

This module contains adapters for converting FastAPI request objects
to domain-specific request contexts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import Request

from src.core.domain.request_context import RequestContext

logger = logging.getLogger(__name__)


def fastapi_to_domain_request_context(
    request: Request, attach_original: bool = False
) -> RequestContext:
    """Convert a FastAPI request to a domain request context.
    
    Args:
        request: The FastAPI request object
        attach_original: Whether to attach the original request object to the context
        
    Returns:
        A domain request context
    """
    # Extract headers
    headers = {}
    for header_name, header_value in request.headers.items():
        headers[header_name.lower()] = header_value
    
    # Extract cookies
    cookies = {}
    for cookie_name, cookie_value in request.cookies.items():
        cookies[cookie_name] = cookie_value
    
    # Create the context
    context = RequestContext(
        headers=headers,
        cookies=cookies,
        client_host=request.client.host if hasattr(request, "client") and request.client else None,
        app_state=getattr(request.app, "state", None),
        state=getattr(request.state, "request_state", {}),
    )
    
    # Attach the original request if requested
    if attach_original:
        context.original_request = request
    
    return context


def extract_request_info(request: Request) -> Dict[str, Any]:
    """Extract useful information from a FastAPI request for logging or context.
    
    This function extracts common request attributes that are useful for
    debugging, logging, and context tracking.
    
    Args:
        request: The FastAPI request object
        
    Returns:
        A dictionary of request information
    """
    info: Dict[str, Any] = {
        "method": request.method,
        "url": str(request.url),
        "client_host": getattr(request.client, "host", "unknown") if hasattr(request, "client") else "unknown",
        "headers": {
            k.lower(): v for k, v in request.headers.items()
            if k.lower() not in ("authorization", "x-api-key")
        },
    }
    
    # Add session ID if available
    session_id = request.headers.get("x-session-id")
    if session_id:
        info["session_id"] = session_id
    
    return info
