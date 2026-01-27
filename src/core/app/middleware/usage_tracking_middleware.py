"""Usage tracking middleware for recording request/response metrics.

This middleware records usage metrics at the request entry point and response
exit point, capturing timing, user context, and status codes.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

if TYPE_CHECKING:
    from src.core.interfaces.usage_recording_interface import IUsageRecordingService

logger = logging.getLogger(__name__)


class UsageTrackingMiddleware:
    """Pure ASGI middleware for tracking usage metrics that doesn't buffer streaming responses.

    This middleware:
    - Records request timing at entry point
    - Captures user-agent and proxy user context
    - Records response timing and status codes
    - Stores timing information in request state for downstream use

    Avoids BaseHTTPMiddleware which buffers entire streaming responses.
    """

    def __init__(
        self,
        app: ASGIApp,
        usage_recording_service: IUsageRecordingService,
    ):
        """Initialize the usage tracking middleware.

        Args:
            app: The ASGI application
            usage_recording_service: Service for recording usage metrics
        """
        self.app = app
        self._usage_service = usage_recording_service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request and record usage metrics without buffering streams.

        Args:
            scope: ASGI scope
            receive: ASGI receive channel
            send: ASGI send channel
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Record request start time
        request_start_time = time.time()

        # Create request to extract headers
        request = Request(scope, receive)
        user_agent = request.headers.get("user-agent")
        proxy_user = request.headers.get("x-proxy-user")

        # Store timing and context in scope state for downstream use
        if "state" not in scope:
            scope["state"] = {}

        scope["state"]["request_start_time"] = request_start_time
        scope["state"]["user_agent"] = user_agent
        scope["state"]["proxy_user"] = proxy_user

        # Track response timing
        response_started = False
        response_end_time: float | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, response_end_time

            if message["type"] == "http.response.start":
                response_started = True
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                # Final chunk - record completion time
                response_end_time = time.time()
                total_duration_ms = (response_end_time - request_start_time) * 1000
                scope["state"]["response_end_time"] = response_end_time
                scope["state"]["total_duration_ms"] = total_duration_ms

            await send(message)

        # Note: Actual usage recording happens in the route handlers where we have
        # access to session_id, backend_type, model, etc. This middleware just
        # captures timing and context information.

        await self.app(scope, receive, send_wrapper)
