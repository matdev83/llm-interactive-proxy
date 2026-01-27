"""
SSO middleware adapter for FastAPI.

This module provides an adapter that wraps the SSO AuthMiddleware
to work with FastAPI's Starlette middleware system.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.auth.sso.middleware import AuthMiddleware
from src.core.common.json_validation import JSONValidationError, validate_json_structure
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class SSOMiddlewareAdapter:
    """Pure ASGI adapter that integrates SSO AuthMiddleware without buffering streaming responses.

    Avoids BaseHTTPMiddleware which buffers entire streaming responses.
    """

    # Security limits
    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self, app: ASGIApp, sso_middleware: AuthMiddleware):
        """
        Initialize the SSO middleware adapter.

        Args:
            app: FastAPI application
            sso_middleware: SSO authentication middleware instance
        """
        self.app = app
        self.sso_middleware = sso_middleware

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request through SSO authentication without buffering streams.

        Args:
            scope: ASGI scope
            receive: ASGI receive channel
            send: ASGI send channel
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract path from scope
        path = scope.get("path", "")

        # Skip SSO check for auth endpoints
        if path.startswith("/auth/"):
            await self.app(scope, receive, send)
            return

        # Skip SSO check for health/docs endpoints
        if path in ("/health", "/docs", "/openapi.json", "/redoc"):
            await self.app(scope, receive, send)
            return

        # Convert ASGI request to dict format expected by SSO middleware
        # This also reads and caches the body for downstream handlers
        request_dict, cached_receive = await self._convert_request_to_dict(
            scope, receive
        )

        # Call SSO middleware
        try:
            sandbox_response = await self.sso_middleware(request_dict)
        except Exception as e:
            logger.error(f"SSO middleware error: {e}", exc_info=True)
            # On error, return sandbox response for safety
            sandbox_response = (
                await self.sso_middleware.sandbox_handler.generate_login_banner()
            )

        # If sandbox response returned, user is not authenticated
        if sandbox_response is not None:
            await self._send_sandbox_response(send, sandbox_response)
            return

        # User is authenticated - continue to next handler with cached receive
        # so downstream handlers can read the body
        await self.app(scope, cached_receive, send)

    async def _convert_request_to_dict(
        self, scope: Scope, receive: Receive
    ) -> tuple[dict[str, Any], Receive]:
        """Convert ASGI request to dict format and return cached receive for downstream.

        Args:
            scope: ASGI scope
            receive: ASGI receive channel

        Returns:
            Tuple of (request_dict, cached_receive) where cached_receive can be used
            by downstream handlers to read the body again
        """
        # Extract headers from scope
        headers: dict[str, str] = {}
        for header_name_bytes, header_value_bytes in scope.get("headers", []):
            header_name = header_name_bytes.decode("latin-1")
            header_value = header_value_bytes.decode("latin-1")
            headers[header_name] = header_value

        # Try to extract messages from request body for chat completion requests
        messages: list[dict[str, Any]] = []
        method = scope.get("method", "")
        cached_body: bytes | None = None

        if method == "POST":
            try:
                # Read body from ASGI receive channel
                body_chunks: list[bytes] = []
                body_size = 0
                more_body = True

                while more_body:
                    message = await receive()
                    if message["type"] == "http.request":
                        chunk = message.get("body", b"")
                        body_chunks.append(chunk)
                        body_size += len(chunk)
                        more_body = message.get("more_body", False)

                        # Security: Check body size before continuing
                        if body_size > self.MAX_BODY_SIZE:
                            logger.warning(
                                "Request body too large for SSO inspection: %d bytes (limit: %d)",
                                body_size,
                                self.MAX_BODY_SIZE,
                            )
                            break

                if body_chunks:
                    cached_body = b"".join(body_chunks)

                    # Security: Check body size before parsing
                    if len(cached_body) <= self.MAX_BODY_SIZE:
                        body_dict = json.loads(cached_body)
                        # DoS protection: Validate JSON structure (depth and array size)
                        try:
                            validate_json_structure(body_dict)
                            messages = body_dict.get("messages", [])
                        except JSONValidationError as e:
                            logger.warning(
                                "JSON structure validation failed for SSO inspection: %s",
                                e,
                                exc_info=True,
                            )
                            # Continue without messages to prevent DoS
            except json.JSONDecodeError as e:
                logger.debug(
                    "Failed to parse request body as JSON for SSO inspection: %s",
                    e,
                    exc_info=True,
                )
            except Exception as e:
                logger.warning(
                    "Failed to parse request body for SSO inspection: %s",
                    e,
                    exc_info=True,
                )

        # Create cached receive function for downstream handlers
        body_sent = False

        async def cached_receive():
            nonlocal body_sent
            if not body_sent and cached_body is not None:
                body_sent = True
                return {"type": "http.request", "body": cached_body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        request_dict = {
            "headers": headers,
            "messages": messages,
            "method": method,
            "path": scope.get("path", ""),
        }

        return request_dict, cached_receive

    async def _send_sandbox_response(
        self, send: Send, sandbox_response: dict[str, Any]
    ) -> None:
        """Send sandbox response via ASGI messages.

        Args:
            send: ASGI send channel
            sandbox_response: Sandbox response dictionary
        """
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )

        body = json.dumps(sandbox_response).encode("utf-8")
        await send({"type": "http.response.body", "body": body})
