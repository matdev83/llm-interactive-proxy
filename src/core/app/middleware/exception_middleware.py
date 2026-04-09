from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from src.core.common.exceptions import LLMProxyError
from src.core.domain.client_termination import (
    ClientEndOfSessionSignal,
    ClientTerminationReason,
)
from src.core.interfaces.client_end_of_session_service_interface import (
    IClientEndOfSessionService,
)
from src.core.interfaces.di_interface import IServiceProvider
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send


class DomainExceptionMiddleware:
    """Pure ASGI middleware that translates domain exceptions to HTTP responses.

    Centralized middleware that catches project-specific exceptions
    (LLMProxyError and subclasses) and renders consistent JSON error
    payloads, while logging with appropriate severity. Unknown errors
    are mapped to HTTP 500 with a generic body to avoid leaking internals.

    Also handles client cancellation (CancelledError) by reporting
    client termination in shielded context (Requirement 1.2, 3.8).

    Intentional behavior: keep transport concerns here so that core
    adapters/services remain domain-centric.

    Avoids BaseHTTPMiddleware which buffers entire streaming responses.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._logger = logging.getLogger(__name__)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Compatibility path for call sites expecting BaseHTTPMiddleware.

        The project intentionally avoids BaseHTTPMiddleware to prevent buffering
        streaming responses, but some tests/legacy code call `dispatch()`
        directly. This method mirrors the exception semantics of `__call__`.
        """

        try:
            response = await call_next(request)
            if isinstance(response, Response):
                return response
            # Defensive: some callers/tests use call_next returning None.
            return JSONResponse(status_code=204, content=None)
        except asyncio.CancelledError:
            await self._report_client_termination_if_applicable(
                request, ClientTerminationReason.CLIENT_CANCELLED
            )
            raise
        except LLMProxyError as e:
            if 400 <= int(getattr(e, "status_code", 500)) < 500:
                self._logger.warning("Domain error: %s", e, exc_info=True)
            else:
                self._logger.error("Domain error: %s", e, exc_info=True)

            headers = _resolve_retry_after_header(e)
            return JSONResponse(
                status_code=int(getattr(e, "status_code", 500)),
                content=e.to_dict(),
                headers=headers,
            )
        except Exception as e:
            self._logger.error("Unhandled exception: %s", e, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "message": "Internal Server Error",
                        "type": "InternalError",
                    }
                },
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request and handle exceptions without buffering streams.

        Args:
            scope: ASGI scope
            receive: ASGI receive channel
            send: ASGI send channel
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Any) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            # Requirement 1.2, 3.8: Report client cancellation as termination
            request = Request(scope, receive)
            await self._report_client_termination_if_applicable(
                request, ClientTerminationReason.CLIENT_CANCELLED
            )
            raise
        except LLMProxyError as e:
            # 4xx -> warning; 5xx -> error
            if 400 <= int(getattr(e, "status_code", 500)) < 500:
                self._logger.warning("Domain error: %s", e, exc_info=True)
            else:
                self._logger.error("Domain error: %s", e, exc_info=True)

            if response_started:
                self._logger.error(
                    "Cannot send domain error response: response already started"
                )
                return

            content = e.to_dict()
            status_code = int(getattr(e, "status_code", 500))
            headers = _resolve_retry_after_header(e)
            await self._send_error_response(send, status_code, content, headers)
        except Exception as e:  # Fallback for unexpected errors
            self._logger.error("Unhandled exception: %s", e, exc_info=True)

            if response_started:
                self._logger.error(
                    "Cannot send internal error response: response already started"
                )
                return

            await self._send_error_response(
                send,
                500,
                {
                    "error": {
                        "message": "Internal Server Error",
                        "type": "InternalError",
                    }
                },
                None,
            )

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

    async def _report_client_termination_if_applicable(
        self, request: Request, reason: ClientTerminationReason
    ) -> None:
        """Report client termination in shielded context if session context is available.

        This method ensures termination reporting executes even if the request
        task is cancelled (Requirement 3.8). It only reports if session context
        can be resolved (Requirement 1.6).

        Args:
            request: The FastAPI request object
            reason: The termination reason
        """
        # Get service provider from app.state (may not be available)
        try:
            service_provider = getattr(request.app.state, "service_provider", None)
            if service_provider is None or not isinstance(
                service_provider, IServiceProvider
            ):
                return
        except asyncio.CancelledError:
            # Propagate cancellation - termination reporting should not block cancellation
            raise
        except (AttributeError, RuntimeError, TypeError) as e:
            # Catch specific exceptions from attribute access/type checking
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Failed to get service_provider from request.app.state during client termination reporting: %s",
                    e,
                    exc_info=True,
                )
            return
        except Exception as e:
            # Fallback for unexpected errors - fail-open with logging for debugging
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Unexpected error getting service_provider from request.app.state during client termination reporting: %s",
                    e,
                    exc_info=True,
                )
            return

        # Get client EoS service (optional - may not be registered)
        try:
            client_eos_service = service_provider.get_service(
                IClientEndOfSessionService
            )
            if client_eos_service is None:
                return
        except asyncio.CancelledError:
            # Propagate cancellation - termination reporting should not block cancellation
            raise
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
            # Catch specific exceptions from service provider
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Failed to get IClientEndOfSessionService from service_provider: %s",
                    e,
                    exc_info=True,
                )
            return
        except Exception as e:
            # Fallback for unexpected errors - fail-open but log at WARNING level for visibility
            # Unexpected errors during service provider access should be visible in production logs
            self._logger.warning(
                "Unexpected error getting IClientEndOfSessionService from service_provider: %s",
                e,
                exc_info=True,
            )
            return

        # Create RequestContext from FastAPI request to resolve SessionKey
        try:
            context = fastapi_to_domain_request_context(request)
            # Extract request_id from request.state if available (for SessionKey resolution)
            request_id = getattr(request.state, "request_id", None)
            if request_id:
                context.request_id = request_id
            session_key = resolve_session_key_from_request_context(context)
            if session_key is None:
                # Requirement 1.6: No attribution without session context
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Cannot report client termination: session_key cannot be resolved",
                        extra={"reason": reason.value},
                    )
                return

            # Shield termination reporting to ensure it executes even if task is cancelled
            signal = ClientEndOfSessionSignal(
                session_key=session_key,
                observed_at=datetime.now(timezone.utc),
                reason=reason,
                details="HTTP non-streaming cancellation detected",
            )
            await asyncio.shield(client_eos_service.report_client_termination(signal))
        except asyncio.CancelledError:
            # Propagate cancellation - termination reporting should not block cancellation
            # Note: asyncio.shield should prevent this, but handle explicitly for safety
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            # Catch specific exceptions from request context conversion, session key resolution,
            # or signal construction (e.g., invalid arguments, missing attributes)
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    "Failed to report client termination for cancellation (context/signal error): %s",
                    exc,
                    exc_info=True,
                    extra={
                        "reason": reason.value,
                        "error_code": "CLIENT_TERMINATION_REPORT_FAILED",
                        "exception_type": type(exc).__name__,
                    },
                )
        except Exception as exc:
            # Fail-open: log but don't raise - termination reporting is best-effort
            # Design.md line 445: Log with high-visibility error code
            # Catch-all for unexpected errors (e.g., from report_client_termination)
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    "Failed to report client termination for cancellation: %s",
                    exc,
                    exc_info=True,
                    extra={
                        "reason": reason.value,
                        "error_code": "CLIENT_TERMINATION_REPORT_FAILED",
                    },
                )


def _build_retry_after_header(reset_at: float | int | None) -> dict[str, str] | None:
    """Compute a Retry-After header based on a reset timestamp."""

    if reset_at is None:
        return None

    # Allow ints for compatibility with callers; cast to float for math ops
    reset_at_float = float(reset_at)
    now = time.time()
    delay_seconds = max(0.0, reset_at_float - now)

    if delay_seconds <= 0:
        return {"Retry-After": "0"}

    return {"Retry-After": str(math.ceil(delay_seconds))}


def _resolve_retry_after_header(exc: LLMProxyError) -> dict[str, str] | None:
    reset_at = getattr(exc, "reset_at", None)
    if isinstance(reset_at, int | float):
        return _build_retry_after_header(float(reset_at))

    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        retry_after = details.get("retry_after")
        if isinstance(retry_after, int | float):
            return _build_retry_after_header(time.time() + float(retry_after))

    return None
