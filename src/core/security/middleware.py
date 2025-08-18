"""
Security middleware for API key and token authentication.
"""

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Middleware for API key authentication.

    This middleware checks for a valid API key in the Authorization header
    or the api_key query parameter.
    """

    def __init__(
        self,
        app: Any,
        valid_keys: Iterable[str],
        bypass_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.valid_keys = set(valid_keys)
        self.bypass_paths = bypass_paths or ["/docs", "/openapi.json", "/redoc"]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process the request and check for a valid API key.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            The response from the next middleware or route handler
        """
        # Check if the path is in the bypass list
        if request.url.path in self.bypass_paths:
            response: Response = await call_next(request)
            return response

        # Check for API key in header
        auth_header = request.headers.get("Authorization")
        api_key = None

        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header.replace("Bearer ", "")

        # Check for API key in query parameter
        if not api_key:
            api_key = request.query_params.get("api_key")

        # Validate the API key
        if not api_key or api_key not in self.valid_keys:
            logger.warning(
                "Invalid or missing API key for %s %s from client %s",
                request.method,
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=401, content={"detail": "Invalid or missing API key"}
            )

        # API key is valid, continue processing
        response2: Response = await call_next(request)
        return response2


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for token-based authentication.

    This middleware checks for a valid token in the X-Auth-Token header.
    """

    def __init__(
        self,
        app: Any,
        valid_token: str,
        bypass_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.valid_token = valid_token
        self.bypass_paths = bypass_paths or ["/docs", "/openapi.json", "/redoc"]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process the request and check for a valid token.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            The response from the next middleware or route handler
        """
        # Skip authentication for certain paths
        if request.url.path in self.bypass_paths:
            response: Response = await call_next(request)
            return response

        # Check for token in header
        token = request.headers.get("X-Auth-Token")

        # Validate the token
        if not token or token != self.valid_token:
            logger.warning(
                "Invalid or missing auth token for %s %s from client %s",
                request.method,
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=401, content={"detail": "Invalid or missing auth token"}
            )

        # Token is valid, continue processing
        response3: Response = await call_next(request)
        return response3
