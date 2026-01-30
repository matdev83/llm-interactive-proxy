from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    LLMProxyError,
    LoopDetectionError,
    RateLimitExceededError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryAfterHeader:
    """Typed representation of a Retry-After HTTP header."""

    value: str

    def to_dict(self) -> dict[str, str]:
        """Convert to dict for use with JSONResponse."""
        return {"Retry-After": self.value}


def build_retry_after_header(reset_at: float | None) -> RetryAfterHeader | None:
    """Compute a standards-compliant Retry-After header from a reset timestamp.

    Args:
        reset_at: Unix timestamp when rate limit resets, or None

    Returns:
        RetryAfterHeader object with the header value, or None
    """
    if reset_at is None:
        return None

    now = time.time()
    if reset_at > now:
        delay_seconds = reset_at - now
    else:
        delay_seconds = 0

    if delay_seconds <= 0:
        return RetryAfterHeader(value="0")

    return RetryAfterHeader(value=str(math.ceil(delay_seconds)))


def resolve_retry_after_header(exc: LLMProxyError) -> RetryAfterHeader | None:
    reset_at = getattr(exc, "reset_at", None)
    if isinstance(reset_at, int | float):
        return build_retry_after_header(float(reset_at))

    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        retry_after = details.get("retry_after")
        if isinstance(retry_after, int | float):
            return build_retry_after_header(time.time() + float(retry_after))

    return None


def create_exception_handler() -> (
    Callable[[Request, Exception], Coroutine[Any, Any, Response]]
):
    """Create an exception handler for the application that maps domain exceptions to HTTP responses."""

    async def exception_handler(request: Request, exc: Exception) -> Response:
        """Handle exceptions and convert them to appropriate HTTP responses."""
        # Domain exceptions - convert to appropriate HTTP responses
        if isinstance(exc, LLMProxyError):
            # Get status code and response content directly from the exception
            status_code = exc.status_code
            content = exc.to_dict()

            # Add additional headers for rate limit errors
            header = resolve_retry_after_header(exc)
            headers = header.to_dict() if header else None

            return JSONResponse(
                status_code=status_code, content=content, headers=headers
            )

        # FastAPI HTTPExceptions - pass through
        if isinstance(exc, HTTPException):
            detail = exc.detail

            if isinstance(detail, dict):
                content = detail
            else:
                content = {
                    "error": {
                        "message": str(detail),
                        "type": "http_error",
                    }
                }

            return JSONResponse(
                status_code=exc.status_code,
                content=content,
                headers=getattr(exc, "headers", None),
            )

        # Unhandled exceptions - log and return 500
        # Use exc_info tuple to preserve traceback (exception handler context may not have sys.exc_info())
        logger.error(
            "Unhandled exception: %s",
            exc,
            exc_info=(type(exc), exc, getattr(exc, "__traceback__", None)),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "An unexpected error occurred",
                    "type": "server_error",
                }
            },
        )

    return exception_handler


def register_exception_handlers(app: Any) -> None:
    """Register all exception handlers for the FastAPI application."""
    handler = create_exception_handler()

    # Register handlers for domain exceptions
    app.exception_handler(LLMProxyError)(handler)
    app.exception_handler(AuthenticationError)(handler)
    app.exception_handler(ConfigurationError)(handler)
    app.exception_handler(BackendError)(handler)
    app.exception_handler(RateLimitExceededError)(handler)
    app.exception_handler(ServiceUnavailableError)(handler)
    app.exception_handler(LoopDetectionError)(handler)

    # Register handler for HTTPException
    app.exception_handler(HTTPException)(handler)

    # Register handler for generic exceptions
    app.exception_handler(Exception)(handler)
