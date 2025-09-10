from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        log_requests: bool = False,
        log_responses: bool = False,
    ):
        super().__init__(app)
        self.log_requests = log_requests
        self.log_responses = log_responses

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if self.log_requests:
            logger.info(f"Request: {request.method} {request.url}")

        response = await call_next(request)

        if self.log_responses:
            logger.info(f"Response status: {response.status_code}")

        return response
