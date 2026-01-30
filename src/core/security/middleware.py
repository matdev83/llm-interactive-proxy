"""Security middleware for API key and token authentication."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from fastapi import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from src.core.common.logging_utils import redact_sensitive_value

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


class APIKeyMiddleware:
    """Pure ASGI middleware for API key authentication that doesn't buffer streaming responses.

    This middleware checks for a valid API key in the Authorization header
    or the api_key query parameter.

    Avoids BaseHTTPMiddleware which buffers entire streaming responses.
    """

    def __init__(
        self,
        app: ASGIApp,
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
        self.app = app
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

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Compatibility path for call sites expecting BaseHTTPMiddleware.

        The project intentionally uses pure ASGI middleware to avoid buffering
        streaming responses, but some integration tests patch `dispatch()`.
        This method preserves the same authentication semantics as `__call__`.
        """

        path = getattr(getattr(request, "url", None), "path", None) or ""
        if path in self.bypass_paths:
            return await call_next(request)

        client_ip: str | None = None
        try:
            if request.client:
                client_ip = request.client.host
        except Exception:
            client_ip = None

        if client_ip and client_ip in self.trusted_ips:
            logger.info("Bypassing authentication for trusted IP: %s", client_ip)
            return await call_next(request)

        # Check if auth is disabled for tests or development using DI when available
        app_state_service: IApplicationState | None = None
        injected_service = getattr(self, "app_state_service", None)
        if injected_service is not None:
            try:
                if hasattr(injected_service, "get_setting"):
                    app_state_service = injected_service  # type: ignore[assignment]
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to access injected app_state_service: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None
            except Exception as e:
                logger.warning(
                    "Unexpected error accessing injected app_state_service: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None

        if app_state_service is None:
            try:
                provider = getattr(request.app.state, "service_provider", None)
                if provider is not None:
                    app_state_service = provider.get_service(IApplicationState)  # type: ignore[type-abstract]
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to get app_state_service from provider: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None
            except Exception as e:
                logger.warning(
                    "Unexpected error getting app_state_service from provider: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None

        disable_auth = (
            app_state_service.get_setting("disable_auth", False)
            if app_state_service is not None
            else getattr(request.app.state, "disable_auth", False)
        )
        if disable_auth:
            return await call_next(request)

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
            logger.info("Skipping auth - disabled in app_config")
            return await call_next(request)

        if client_ip:
            blocked_response = await self._maybe_reject_for_bruteforce(client_ip)
            if blocked_response is not None:
                status_code, content, headers = blocked_response
                return JSONResponse(
                    status_code=status_code, content=content, headers=headers
                )

        api_key: str | None = None
        auth_header = request.headers.get("authorization") or request.headers.get(
            "Authorization"
        )
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header.replace("Bearer ", "", 1)

        if not api_key:
            api_key = request.headers.get("x-goog-api-key") or request.headers.get(
                "X-Goog-Api-Key"
            )

        if not api_key:
            try:
                api_key = request.query_params.get("api_key")
            except Exception:
                api_key = None

        app_state_keys: set[str] = set()
        client_api_key: str | None = None
        if app_state_service is not None:
            try:
                client_api_key = app_state_service.get_setting("client_api_key")
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to get client_api_key from app_state_service: %s",
                    e,
                    exc_info=True,
                )
                client_api_key = None
            except Exception as e:
                logger.warning(
                    "Unexpected error getting client_api_key from app_state_service: %s",
                    e,
                    exc_info=True,
                )
                client_api_key = None
        if not client_api_key:
            client_api_key = getattr(request.app.state, "client_api_key", None)
        if client_api_key:
            app_state_keys.add(client_api_key)

        all_valid_keys: set[str] = self.valid_keys | app_state_keys

        method = request.method
        if not api_key or api_key not in all_valid_keys:
            logger.warning(
                "Invalid or missing API key for %s %s from client %s",
                method,
                path,
                client_ip or "unknown",
            )
            if client_ip:
                await self._register_failed_attempt(client_ip)
            return JSONResponse(
                status_code=401,
                content={"detail": HTTP_401_UNAUTHORIZED_MESSAGE},
            )

        if client_ip:
            await self._register_successful_attempt(client_ip)
        return await call_next(request)

    async def _maybe_reject_for_bruteforce(
        self, client_ip: str
    ) -> tuple[int, dict[str, Any], dict[str, str] | None] | None:
        """Return 429 response data when the client IP is temporarily blocked.

        Returns:
            Tuple of (status_code, content, headers) if blocked, None otherwise
        """
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
                return (
                    429,
                    {
                        "detail": HTTP_429_TOO_MANY_REQUESTS_MESSAGE,
                        "retry_after_seconds": wait_seconds,
                    },
                    {"Retry-After": str(wait_seconds)},
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request and check for valid API key without buffering streams.

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

        # Check if the path is in the bypass list
        if path in self.bypass_paths:
            await self.app(scope, receive, send)
            return

        # Extract client IP from scope
        client = scope.get("client")
        client_ip = client[0] if client and len(client) > 0 else None

        # Check if the client IP is in the trusted IPs list
        if client_ip and client_ip in self.trusted_ips:
            logger.info("Bypassing authentication for trusted IP: %s", client_ip)
            await self.app(scope, receive, send)
            return

        # Create Request object temporarily for app.state access
        request = Request(scope, receive)

        # Check if auth is disabled for tests or development using DI when available
        app_state_service: IApplicationState | None = None
        # Prefer a test-injected app_state_service when present (unit tests stub this attribute)
        injected_service = getattr(self, "app_state_service", None)
        if injected_service is not None:
            try:
                # Basic duck-typing: ensure required method exists
                if hasattr(injected_service, "get_setting"):
                    app_state_service = injected_service  # type: ignore[assignment]
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to access injected app_state_service: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None
            except Exception as e:
                logger.warning(
                    "Unexpected error accessing injected app_state_service: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None
        if app_state_service is None:
            try:
                provider = getattr(request.app.state, "service_provider", None)
                if provider is not None:
                    app_state_service = provider.get_service(IApplicationState)  # type: ignore[type-abstract]
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to get app_state_service from provider: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None
            except Exception as e:
                logger.warning(
                    "Unexpected error getting app_state_service from provider: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None

        if app_state_service is not None:
            disable_auth = app_state_service.get_setting("disable_auth", False)
        else:
            disable_auth = getattr(request.app.state, "disable_auth", False)
        if disable_auth:
            # Auth is disabled, skip validation
            await self.app(scope, receive, send)
            return

        # Short-circuit for clients currently blocked for repeated failures
        if client_ip:
            blocked_response = await self._maybe_reject_for_bruteforce(client_ip)
            if blocked_response is not None:
                status_code, content, headers = blocked_response
                await self._send_error_response(send, status_code, content, headers)
                return

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
            await self.app(scope, receive, send)
            return

        # Extract headers from scope
        headers_dict: dict[str, str] = {}
        for header_name_bytes, header_value_bytes in scope.get("headers", []):
            header_name = header_name_bytes.decode("latin-1").lower()
            header_value = header_value_bytes.decode("latin-1")
            headers_dict[header_name] = header_value

        # Check for API key in header
        auth_header: str | None = headers_dict.get("authorization")
        api_key: str | None = None

        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header.replace("Bearer ", "", 1)

        # Debug: log detected API key (masked) for test troubleshooting
        try:
            masked = redact_sensitive_value(api_key)
            logger.debug("Detected API key in request: %s", masked)
        except Exception as e:
            logger.debug("Error masking API key for logging: %s", e, exc_info=True)

        # Check for Gemini API key in x-goog-api-key header
        if not api_key:
            gemini_api_key = headers_dict.get("x-goog-api-key")
            if gemini_api_key:
                # Log the detected Gemini API key for debugging
                logger.debug("Detected Gemini API key in x-goog-api-key header")
                api_key = gemini_api_key

        # Check for API key in query parameter
        if not api_key:
            query_string = scope.get("query_string", b"").decode("latin-1")
            if query_string:
                try:
                    query_params = parse_qs(query_string, keep_blank_values=False)
                    api_key = query_params.get("api_key", [None])[0]  # type: ignore[assignment]
                except Exception as e:
                    logger.debug(
                        "Failed to parse query string for API key: %s", e, exc_info=True
                    )

        # Check for additional API keys in app.state (for tests)
        app_state_keys: set[str] = set()
        client_api_key = None
        if app_state_service is not None:
            try:
                client_api_key = app_state_service.get_setting("client_api_key")
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to get client_api_key from app_state_service: %s",
                    e,
                    exc_info=True,
                )
                client_api_key = None
            except Exception as e:
                logger.warning(
                    "Unexpected error getting client_api_key from app_state_service: %s",
                    e,
                    exc_info=True,
                )
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
        method = scope.get("method", "UNKNOWN")
        if not api_key or api_key not in all_valid_keys:
            logger.warning(
                "Invalid or missing API key for %s %s from client %s",
                method,
                path,
                client_ip or "unknown",
            )
            if client_ip:
                await self._register_failed_attempt(client_ip)
            await self._send_error_response(
                send, 401, {"detail": HTTP_401_UNAUTHORIZED_MESSAGE}, None
            )
            return

        # API key is valid, continue processing
        if client_ip:
            await self._register_successful_attempt(client_ip)
        await self.app(scope, receive, send)

    async def _send_error_response(
        self,
        send: Send,
        status_code: int,
        content: dict[str, Any],
        headers: dict[str, str] | None,
    ) -> None:
        """Send error response via ASGI messages.

        Args:
            send: ASGI send channel
            status_code: HTTP status code
            content: Response content dictionary
            headers: Optional headers dictionary
        """
        response_headers = [(b"content-type", b"application/json")]
        if headers:
            for header_name, header_value in headers.items():
                response_headers.append(
                    (header_name.encode("latin-1"), header_value.encode("latin-1"))
                )

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": response_headers,
            }
        )

        body = json.dumps(content).encode("utf-8")
        await send({"type": "http.response.body", "body": body})


class AuthMiddleware:
    """Pure ASGI middleware for token-based authentication that doesn't buffer streaming responses.

    This middleware checks for a valid token in the X-Auth-Token header.

    Avoids BaseHTTPMiddleware which buffers entire streaming responses.
    """

    def __init__(
        self, app: ASGIApp, valid_token: str, bypass_paths: list[str] | None = None
    ) -> None:
        self.app = app
        self.valid_token = valid_token
        self.bypass_paths = bypass_paths or ["/docs", "/openapi.json", "/redoc"]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Compatibility path for call sites expecting BaseHTTPMiddleware.

        The project intentionally uses pure ASGI middleware to avoid buffering
        streaming responses, but some unit tests call `dispatch()`.
        This method preserves the same authentication semantics as `__call__`.
        """
        path = getattr(getattr(request, "url", None), "path", None) or ""
        if path in self.bypass_paths:
            return await call_next(request)

        # Respect runtime auth disabling
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

        disable_auth = (
            app_state_service.get_setting("disable_auth", False)
            if app_state_service is not None
            else getattr(request.app.state, "disable_auth", False)
        )

        if disable_auth:
            return await call_next(request)

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
            return await call_next(request)

        # Check for token in header
        # Support both lowercase and capitalized for mock compatibility
        token = request.headers.get("x-auth-token") or request.headers.get(
            "X-Auth-Token"
        )

        # Extract client IP for logging
        client_ip = None
        try:
            if request.client:
                client_ip = request.client.host
        except Exception:
            client_ip = None

        method = request.method

        # Validate the token
        if not token or token != self.valid_token:
            logger.warning(
                "Invalid or missing auth token for %s %s from client %s",
                method,
                path,
                client_ip or "unknown",
            )
            return JSONResponse(
                status_code=401,
                content={"detail": HTTP_401_UNAUTHORIZED_MESSAGE},
            )

        # Token is valid, continue processing
        return await call_next(request)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request and check for valid token without buffering streams.

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

        # Skip authentication for certain paths
        if path in self.bypass_paths:
            await self.app(scope, receive, send)
            return

        # Create Request object temporarily for app.state access
        request = Request(scope, receive)

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
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to get app_state_service from provider: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None
            except Exception as e:
                logger.warning(
                    "Unexpected error getting app_state_service from provider: %s",
                    e,
                    exc_info=True,
                )
                app_state_service = None

        if app_state_service is not None:
            disable_auth = app_state_service.get_setting("disable_auth", False)
        else:
            disable_auth = getattr(request.app.state, "disable_auth", False)

        if disable_auth:
            await self.app(scope, receive, send)
            return

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
            await self.app(scope, receive, send)
            return

        # Extract headers from scope
        headers_dict: dict[str, str] = {}
        for header_name_bytes, header_value_bytes in scope.get("headers", []):
            header_name = header_name_bytes.decode("latin-1").lower()
            header_value = header_value_bytes.decode("latin-1")
            headers_dict[header_name] = header_value

        # Check for token in header
        token: str | None = headers_dict.get("x-auth-token")

        # Extract client IP for logging
        client = scope.get("client")
        client_ip = client[0] if client and len(client) > 0 else None
        method = scope.get("method", "UNKNOWN")

        # Validate the token
        if not token or token != self.valid_token:
            logger.warning(
                "Invalid or missing auth token for %s %s from client %s",
                method,
                path,
                client_ip or "unknown",
            )
            await self._send_error_response(
                send, 401, {"detail": HTTP_401_UNAUTHORIZED_MESSAGE}, None
            )
            return

        # Token is valid, continue processing
        await self.app(scope, receive, send)

    async def _send_error_response(
        self,
        send: Send,
        status_code: int,
        content: dict[str, Any],
        headers: dict[str, str] | None,
    ) -> None:
        """Send error response via ASGI messages.

        Args:
            send: ASGI send channel
            status_code: HTTP status code
            content: Response content dictionary
            headers: Optional headers dictionary
        """
        response_headers = [(b"content-type", b"application/json")]
        if headers:
            for header_name, header_value in headers.items():
                response_headers.append(
                    (header_name.encode("latin-1"), header_value.encode("latin-1"))
                )

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": response_headers,
            }
        )

        body = json.dumps(content).encode("utf-8")
        await send({"type": "http.response.body", "body": body})
