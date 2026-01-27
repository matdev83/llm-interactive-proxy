"""
Request processing middleware for handling cross-cutting concerns like API key redaction.

Note: Command filtering is no longer handled by middleware - it is handled by the
non-forwardable message tagging system.

This module provides a pluggable middleware system that can process requests
before they are sent to any backend without coupling the redaction logic to individual connectors.

"""

from __future__ import annotations

import logging

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class CustomHeaderMiddleware:
    """Pure ASGI middleware for handling custom headers without buffering streaming responses.

    Extracts x-session-id header and stores it in scope state for downstream handlers.
    Avoids BaseHTTPMiddleware which buffers entire streaming responses.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request and extract custom headers without buffering streams.

        Args:
            scope: ASGI scope
            receive: ASGI receive channel
            send: ASGI send channel
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract x-session-id from headers
        session_id = None
        for header_name_bytes, header_value_bytes in scope.get("headers", []):
            if header_name_bytes.decode("latin-1").lower() == "x-session-id":
                session_id = header_value_bytes.decode("latin-1")
                break

        if session_id:
            # Store in scope state for downstream handlers
            if "state" not in scope:
                scope["state"] = {}
            scope["state"]["session_id"] = session_id

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Session ID from headers: %s", session_id)

        await self.app(scope, receive, send)
