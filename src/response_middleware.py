"""Response processing middleware.

This module handles cross-cutting concerns like loop detection and API key
redaction for responses returned by any backend without coupling the logic to
individual connectors.

Note: For request processing (e.g., API key redaction), see
``request_middleware.py``.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class RetryAfterMiddleware:
    """Pure ASGI middleware passthrough that doesn't buffer streaming responses.

    This middleware is a no-op passthrough. It exists for potential future
    retry-after header handling but currently does nothing.

    Avoids BaseHTTPMiddleware which buffers entire streaming responses.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass through request without modification.

        Args:
            scope: ASGI scope
            receive: ASGI receive channel
            send: ASGI send channel
        """
        await self.app(scope, receive, send)
