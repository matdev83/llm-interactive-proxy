"""Middleware that prevents backend request loops."""

from __future__ import annotations

import json

from src.core.security.loop_prevention import LOOP_GUARD_HEADER
from starlette.types import ASGIApp, Receive, Scope, Send


class LoopPreventionMiddleware:
    """Pure ASGI middleware that rejects loop requests without buffering streams."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Check for loop guard header
        for header_name_bytes, _header_value_bytes in scope.get("headers", []):
            if header_name_bytes.decode("latin-1").lower() == LOOP_GUARD_HEADER.lower():
                # Loop detected - send 508 error response
                await send(
                    {
                        "type": "http.response.start",
                        "status": 508,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                body = json.dumps({"detail": "Request loop detected"}).encode("utf-8")
                await send(
                    {
                        "type": "http.response.body",
                        "body": body,
                    }
                )
                return

        await self.app(scope, receive, send)
