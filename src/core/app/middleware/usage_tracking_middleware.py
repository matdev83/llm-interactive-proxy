"""Usage tracking middleware for recording request/response metrics.

This middleware records usage metrics at the request entry point and response
exit point, capturing timing, user context, and status codes.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from src.core.interfaces.usage_recording_interface import IUsageRecordingService

logger = logging.getLogger(__name__)


class UsageTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware for tracking usage metrics at request/response boundaries.

    This middleware:
    - Records request timing at entry point
    - Captures user-agent and proxy user context
    - Records response timing and status codes
    - Stores timing information in request state for downstream use
    """

    def __init__(
        self,
        app,
        usage_recording_service: IUsageRecordingService,
    ):
        """Initialize the usage tracking middleware.

        Args:
            app: The ASGI application
            usage_recording_service: Service for recording usage metrics
        """
        super().__init__(app)
        self._usage_service = usage_recording_service

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process request and record usage metrics.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            The response from downstream handlers
        """
        # Record request start time
        request_start_time = time.time()

        # Store timing in request state for downstream use
        request.state.request_start_time = request_start_time

        # Extract user context
        user_agent = request.headers.get("user-agent")
        proxy_user = request.headers.get("x-proxy-user")

        # Store user context in request state for downstream use
        request.state.user_agent = user_agent
        request.state.proxy_user = proxy_user

        # Call next middleware/handler
        response = await call_next(request)

        # Record response completion time
        response_end_time = time.time()
        total_duration_ms = (response_end_time - request_start_time) * 1000

        # Store response timing in request state
        request.state.response_end_time = response_end_time
        request.state.total_duration_ms = total_duration_ms

        # Note: Actual usage recording happens in the route handlers where we have
        # access to session_id, backend_type, model, etc. This middleware just
        # captures timing and context information.

        return response
