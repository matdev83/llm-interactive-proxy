"""Security middleware for API key and token authentication."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Import HTTP status constants
from src.core.constants import (
    HTTP_401_UNAUTHORIZED_MESSAGE,
    HTTP_429_TOO_MANY_REQUESTS_MESSAGE,
)
from src.core.interfaces.application_state_interface import IApplicationState

logger = logging.getLogger(__name__)


@dataclass
class _BruteForceRecord:
    """Track failed attempts and blocking metadata for a client IP."""

    count: int
    blocked_until: float
    next_block_seconds: float
    expires_at: float


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
        trusted_ips: list[str] | None = None,
        brute_force_enabled: bool = True,
        brute_force_ttl_seconds: int = 900,
        brute_force_max_attempts: int = 5,
        brute_force_initial_block_seconds: int = 30,
        brute_force_block_multiplier: float = 2.0,
        brute_force_max_block_seconds: int = 3600,
    ) -> None:
        super().__init__(app)
        self.valid_keys = set(valid_keys)
        self.bypass_paths = bypass_paths or ["/docs", "/openapi.json", "/redoc"]
        self.trusted_ips = set(trusted_ips or [])
        self.brute_force_enabled = brute_force_enabled and brute_force_max_attempts > 0
        self.brute_force_ttl_seconds = max(brute_force_ttl_seconds, 1)
        self.brute_force_max_attempts = max(brute_force_max_attempts, 1)
        self.brute_force_initial_block_seconds = max(
            brute_force_initial_block_seconds, 1
        )
        self.brute_force_block_multiplier = (
            brute_force_block_multiplier if brute_force_block_multiplier > 1 else 1.0
        )
        self.brute_force_max_block_seconds = max(brute_force_max_block_seconds, 1)
        self._attempts: dict[str, _BruteForceRecord] = {}
        self._attempts_lock = asyncio.Lock()
        self._last_cleanup = 0.0

    async def _maybe_reject_for_bruteforce(self, client_ip: str) -> Response | None:
        """Return a 429 response when the client IP is temporarily blocked."""
        if not self.brute_force_enabled:
            return None

        now = time.time()
        async with self._attempts_lock:
            self._cleanup_locked(now)
            record = self._attempts.get(client_ip)
            if record is None:
                return None
            if record.blocked_until > now:
                wait_seconds = max(0, math.ceil(record.blocked_until - now))
                logger.warning(
                    "Blocking client %s due to repeated invalid API key attempts (wait %ss)",
                    client_ip,
                    wait_seconds,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": HTTP_429_TOO_MANY_REQUESTS_MESSAGE,
                        "retry_after_seconds": wait_seconds,
                    },
                    headers={"Retry-After": str(wait_seconds)},
                )
            if record.expires_at <= now:
                del self._attempts[client_ip]
        return None

    async def _register_failed_attempt(self, client_ip: str) -> None:
        """Record a failed API key attempt for brute-force protection."""
        if not self.brute_force_enabled:
            return

        now = time.time()
        async with self._attempts_lock:
            self._cleanup_locked(now)
            record = self._ensure_record_locked(client_ip, now)
            record.count += 1
            if record.count >= self.brute_force_max_attempts:
                block_seconds = min(
                    record.next_block_seconds, self.brute_force_max_block_seconds
                )
                record.blocked_until = max(record.blocked_until, now + block_seconds)
                next_block = block_seconds * self.brute_force_block_multiplier
                record.next_block_seconds = min(
                    max(math.ceil(next_block), block_seconds),
                    self.brute_force_max_block_seconds,
                )
                logger.info(
                    "Client %s reached brute-force threshold: count=%s block=%ss",
                    client_ip,
                    record.count,
                    block_seconds,
                )
            record.expires_at = max(
                now + self.brute_force_ttl_seconds, record.blocked_until
            )

    async def _register_successful_attempt(self, client_ip: str) -> None:
        """Reset brute-force tracking after a successful authentication."""
        if not self.brute_force_enabled:
            return

        async with self._attempts_lock:
            if client_ip in self._attempts:
                logger.debug("Resetting brute-force tracker for client %s", client_ip)
                del self._attempts[client_ip]

    def _ensure_record_locked(self, client_ip: str, now: float) -> _BruteForceRecord:
        """Ensure a brute-force tracking record exists for the client (lock held)."""
        record = self._attempts.get(client_ip)
        if record is None or record.expires_at <= now:
            record = _BruteForceRecord(
                count=0,
                blocked_until=0.0,
                next_block_seconds=self.brute_force_initial_block_seconds,
                expires_at=now + self.brute_force_ttl_seconds,
            )
            self._attempts[client_ip] = record
        return record

    def _cleanup_locked(self, now: float) -> None:
        """Remove stale brute-force tracking records (lock held)."""
        if not self._attempts:
            return
        if now - self._last_cleanup < self.brute_force_ttl_seconds:
            return

        expired = [
            ip
            for ip, record in self._attempts.items()
            if record.expires_at <= now and record.blocked_until <= now
        ]
        for ip in expired:
            self._attempts.pop(ip, None)
        self._last_cleanup = now

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
            response = await call_next(request)
            return response

        # Check if the client IP is in the trusted IPs list
        client_ip = request.client.host if request.client else None
        if client_ip and client_ip in self.trusted_ips:
            logger.info("Bypassing authentication for trusted IP: %s", client_ip)
            response = await call_next(request)
            return response

        # Short-circuit for clients currently blocked for repeated failures
        if client_ip:
            blocked_response = await self._maybe_reject_for_bruteforce(client_ip)
            if blocked_response is not None:
                return blocked_response

        # Check if auth is disabled for tests or development using DI when available
        app_state_service: IApplicationState | None = None
        # Prefer a test-injected app_state_service when present (unit tests stub this attribute)
        injected_service = getattr(self, "app_state_service", None)
        if injected_service is not None:
            try:
                # Basic duck-typing: ensure required method exists
                if hasattr(injected_service, "get_setting"):
                    app_state_service = injected_service  # type: ignore[assignment]
            except Exception:
                app_state_service = None
        if app_state_service is None:
            try:
                provider = getattr(request.app.state, "service_provider", None)
                if provider is not None:
                    app_state_service = provider.get_service(IApplicationState)  # type: ignore[type-abstract]
            except Exception:
                app_state_service = None

        if app_state_service is not None:
            disable_auth = app_state_service.get_setting("disable_auth", False)
        else:
            disable_auth = getattr(request.app.state, "disable_auth", False)
        if disable_auth:
            # Auth is disabled, skip validation
            response = await call_next(request)
            return response

        # Check if auth is disabled in the app config
        app_config = (
            app_state_service.get_setting("app_config")
            if app_state_service is not None
            else getattr(request.app.state, "app_config", None)
        )
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
        except Exception as e:
            logger.debug("Error masking API key for logging: %s", e)

        # Check for Gemini API key in x-goog-api-key header
        if not api_key:
            gemini_api_key = request.headers.get("x-goog-api-key")
            if gemini_api_key:
                # Log the detected Gemini API key for debugging
                logger.debug("Detected Gemini API key in x-goog-api-key header")
                api_key = gemini_api_key

        # Check for API key in query parameter
        if not api_key:
            api_key = request.query_params.get("api_key")

        # Check for additional API keys in app.state (for tests)
        app_state_keys: set[str] = set()
        client_api_key = None
        if app_state_service is not None:
            try:
                client_api_key = app_state_service.get_setting("client_api_key")
            except Exception:
                client_api_key = None
        if not client_api_key:
            client_api_key = getattr(request.app.state, "client_api_key", None)
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
            if client_ip:
                await self._register_failed_attempt(client_ip)
            return JSONResponse(
                status_code=401, content={"detail": HTTP_401_UNAUTHORIZED_MESSAGE}
            )

        # API key is valid, continue processing
        if client_ip:
            await self._register_successful_attempt(client_ip)
        response = await call_next(request)
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for token-based authentication.

    This middleware checks for a valid token in the X-Auth-Token header.
    """

    def __init__(
        self, app: Any, valid_token: str, bypass_paths: list[str] | None = None
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
            response = await call_next(request)
            return response

        # Respect runtime auth disabling via dependency injection when available
        app_state_service: IApplicationState | None = None
        injected_service = getattr(self, "app_state_service", None)
        if injected_service is not None and hasattr(injected_service, "get_setting"):
            app_state_service = injected_service  # type: ignore[assignment]

        if app_state_service is None:
            try:
                provider = getattr(request.app.state, "service_provider", None)
                if provider is not None:
                    app_state_service = provider.get_service(IApplicationState)  # type: ignore[type-abstract]
            except Exception:
                app_state_service = None

        if app_state_service is not None:
            disable_auth = app_state_service.get_setting("disable_auth", False)
        else:
            disable_auth = getattr(request.app.state, "disable_auth", False)

        if disable_auth:
            response = await call_next(request)
            return response

        app_config = (
            app_state_service.get_setting("app_config")
            if app_state_service is not None
            else getattr(request.app.state, "app_config", None)
        )

        if (
            app_config
            and hasattr(app_config, "auth")
            and getattr(app_config.auth, "disable_auth", False)
        ):
            logger.info("Skipping auth token validation - disabled in app_config")
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
                status_code=401, content={"detail": HTTP_401_UNAUTHORIZED_MESSAGE}
            )

        # Token is valid, continue processing
        response = await call_next(request)
        return response
