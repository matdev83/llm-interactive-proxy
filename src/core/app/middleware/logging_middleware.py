from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class LoggingMiddleware:
    """Pure ASGI logging middleware that doesn't buffer streaming responses.

    This implementation avoids BaseHTTPMiddleware which has a bug that buffers
    entire streaming responses before sending them to the client.
    """

    def __init__(
        self,
        app: ASGIApp,
        log_requests: bool = False,
        log_responses: bool = False,
    ):
        self.app = app
        self.log_requests = log_requests
        self.log_responses = log_responses

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Log request
        if self.log_requests and logger.isEnabledFor(logging.INFO):
            request = Request(scope, receive)
            logger.info("Request: %s %s", request.method, request.url)

        # Wrap send to intercept response
        status_code: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]

                # Log response status immediately, before streaming starts
                if (
                    self.log_responses
                    and logger.isEnabledFor(logging.INFO)
                    and status_code
                ):
                    logger.info("Response status: %s", status_code)

            await send(message)

        await self.app(scope, receive, send_wrapper)
