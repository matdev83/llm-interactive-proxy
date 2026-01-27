"""Middleware for ensuring every request has a unique ID."""

from __future__ import annotations

import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestIDMiddleware:
    """Pure ASGI middleware that adds a unique request ID without buffering streams.

    It checks for X-Request-ID and X-Correlation-ID headers, and falls back
    to generating a new UUID if neither is present.

    Avoids BaseHTTPMiddleware which buffers entire streaming responses.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract request ID from headers
        request_id = None

        for header_name_bytes, header_value_bytes in scope.get("headers", []):
            header_name = header_name_bytes.decode("latin-1").lower()
            if header_name in ("x-request-id", "x-correlation-id"):
                request_id = header_value_bytes.decode("latin-1")
                break

        # Generate if missing
        if not request_id:
            request_id = f"req-{uuid.uuid4().hex[:12]}"

        # Store in scope state
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        # Wrap send to add request ID to response headers
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers_list = list(message.get("headers", []))

                # Check if X-Request-ID already exists
                has_request_id = any(
                    header_name.decode("latin-1").lower() == "x-request-id"
                    for header_name, _ in headers_list
                )

                # Add if missing
                if not has_request_id:
                    headers_list.append((b"x-request-id", request_id.encode("latin-1")))

                message["headers"] = headers_list

            await send(message)

        await self.app(scope, receive, send_wrapper)
