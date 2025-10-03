"""
Request processing middleware for handling cross-cutting concerns like API key redaction and command filtering.


This module provides a pluggable middleware system that can process requests
before they are sent to any backend without coupling the redaction logic to individual connectors.

"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class CustomHeaderMiddleware(BaseHTTPMiddleware):
    """Middleware for handling custom headers."""

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
        # Get the session ID from the request headers
        session_id = request.headers.get("x-session-id")
        if session_id:
            # Store the session ID in the request state
            request.state.session_id = session_id
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Session ID from headers: {session_id}")

        # Call the next middleware or route handler
        response = await call_next(request)

        return response
