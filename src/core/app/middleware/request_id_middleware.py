"""Middleware for ensuring every request has a unique ID."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that adds a unique request ID to every request.
    
    It checks for X-Request-ID and X-Correlation-ID headers, and falls back
    to generating a new UUID if neither is present.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Try to extract from headers
        request_id = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
        
        # If still missing, generate one
        if not request_id:
            request_id = f"req-{uuid.uuid4().hex[:12]}"
            
        # Store in request state for other middlewares and handlers
        request.state.request_id = request_id
        
        # Call next middleware/handler
        response = await call_next(request)
        
        # Ensure the request ID is returned in the response headers for traceability
        if "X-Request-ID" not in response.headers:
            response.headers["X-Request-ID"] = str(request_id)
            
        return response
