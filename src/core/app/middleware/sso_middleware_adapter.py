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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class SSOMiddlewareAdapter(BaseHTTPMiddleware):
    """Adapter that integrates SSO AuthMiddleware with FastAPI."""

    # Security limits
    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self, app: Any, sso_middleware: AuthMiddleware):
        """
        Initialize the SSO middleware adapter.

        Args:
            app: FastAPI application
            sso_middleware: SSO authentication middleware instance
        """
        super().__init__(app)
        self.sso_middleware = sso_middleware

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """
        Process request through SSO authentication.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware in chain

        Returns:
            HTTP response (sandbox response if unauthenticated, or normal response)
        """
        # Skip SSO check for auth endpoints
        if request.url.path.startswith("/auth/"):
            return await call_next(request)  # type: ignore

        # Skip SSO check for health/docs endpoints
        if request.url.path in ["/health", "/docs", "/openapi.json", "/redoc"]:
            return await call_next(request)  # type: ignore

        # Convert FastAPI request to dict format expected by SSO middleware
        request_dict = await self._convert_request_to_dict(request)

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
            return JSONResponse(
                content=sandbox_response,
                status_code=200,
            )

        # User is authenticated - continue to next handler
        return await call_next(request)  # type: ignore

    async def _convert_request_to_dict(self, request: Request) -> dict[str, Any]:
        """
        Convert FastAPI request to dict format.

        Args:
            request: FastAPI request object

        Returns:
            Dictionary representation of request
        """
        # Extract headers
        headers = dict(request.headers)

        # Try to extract messages from request body for chat completion requests
        messages: list[dict[str, Any]] = []
        if request.method == "POST":
            try:
                # Read body and cache it for downstream handlers
                body = await request.body()
                if body:
                    # Cache the body so downstream handlers can read it
                    # This is necessary because request.body() can only be called once
                    async def receive():
                        return {"type": "http.request", "body": body}

                    request._receive = receive  # type: ignore

                    # Security: Check body size before parsing
                    if len(body) <= self.MAX_BODY_SIZE:
                        body_dict = json.loads(body)
                        # DoS protection: Validate JSON structure (depth and array size)
                        try:
                            validate_json_structure(body_dict)
                            messages = body_dict.get("messages", [])
                        except JSONValidationError as e:
                            logger.warning(
                                "JSON structure validation failed for SSO inspection: %s",
                                e,
                            )
                            # Continue without messages to prevent DoS
                    else:
                        logger.warning(
                            "Request body too large for SSO inspection: %d bytes (limit: %d)",
                            len(body),
                            self.MAX_BODY_SIZE,
                        )
            except json.JSONDecodeError as e:
                logger.debug(
                    "Failed to parse request body as JSON for SSO inspection: %s",
                    e,
                )
            except Exception as e:
                logger.warning(
                    "Failed to parse request body for SSO inspection: %s",
                    e,
                    exc_info=True,
                )

        return {
            "headers": headers,
            "messages": messages,
            "method": request.method,
            "path": request.url.path,
        }
