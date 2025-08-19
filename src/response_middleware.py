"""
Response processing middleware for handling cross-cutting concerns like loop detection and API key redaction.


This module provides a pluggable middleware system that can process responses
from any backend without coupling the loop detection logic to individual connectors.

Note: For request processing (e.g., API key redaction), see request_middleware.py
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RetryAfterMiddleware(BaseHTTPMiddleware):
    """Middleware for handling retry-after headers."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process the request before and after the call to the next middleware or route handler.

        Args:
            request: The request object
            call_next: The next middleware or route handler

        Returns:
            The response object
        """
        response = await call_next(request)
        return response
