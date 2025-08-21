"""
Security middleware for API key and token authentication.
"""

import logging
from collections.abc import Awaitable, Callable
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
        valid_keys: list[str],
        bypass_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.valid_keys = set(valid_keys)
        self.bypass_paths = bypass_paths or ["/docs", "/openapi.json", "/redoc"]

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
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
            response = await call_next(request)
            return response

        # Check if auth is disabled for tests or development
        from src.core.services.application_state_service import (
            get_default_application_state,
        )
        
        app_state_service = get_default_application_state()
        # Set the state provider to the current request's app state for this request
        app_state_service.set_state_provider(request.app.state)
        
        disable_auth = app_state_service.get_setting("disable_auth", False)
        if disable_auth:
            # Auth is disabled, skip validation
            response = await call_next(request)
            return response

        # Check if auth is disabled in the app config
        app_config = app_state_service.get_setting("app_config")
        if (
            app_config
            and hasattr(app_config, "auth")
            and getattr(app_config.auth, "disable_auth", False)
        ):
            # Auth is disabled in the config, skip validation
            logger.info("Skipping auth - disabled in app_config")
            response = await call_next(request)
            return response

        # Check for API key in header
        auth_header: str | None = request.headers.get("Authorization")
        api_key: str | None = None

        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header.replace("Bearer ", "", 1)

        # Debug: log detected API key (masked) for test troubleshooting
        try:
            masked: str | None = api_key[:4] + "..." if api_key else None
            logger.debug("Detected API key in request: %s", masked)
        except Exception:
            pass

        # Check for Gemini API key in x-goog-api-key header
        if not api_key:
            api_key = request.headers.get("x-goog-api-key")

        # Check for API key in query parameter
        if not api_key:
            api_key = request.query_params.get("api_key")

        # Check for additional API keys in app.state (for tests)
        app_state_keys: set[str] = set()
        client_api_key = app_state_service.get_setting("client_api_key")
        if client_api_key:
            app_state_keys.add(client_api_key)

        # Combine configured keys with app.state keys
        all_valid_keys: set[str] = self.valid_keys | app_state_keys

        # Validate the API key
        logger.info(
            f"API Key authentication is enabled key_count={len(all_valid_keys)}"
        )
        if not api_key or api_key not in all_valid_keys:
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
        response = await call_next(request)
        return response


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

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
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
            response = await call_next(request)
            return response

        # Check for token in header
        token: str | None = request.headers.get("X-Auth-Token")

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
        response = await call_next(request)
        return response