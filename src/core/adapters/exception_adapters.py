from __future__ import annotations

import logging
import math
import time
import traceback
from collections.abc import Callable, Coroutine
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


def _build_retry_after_header(reset_at: float | None) -> dict[str, str] | None:
    """Compute a standards-compliant Retry-After header from a reset timestamp."""

    if reset_at is None:
        return None

    now = time.time()
    delay_seconds = reset_at - now if reset_at > now else reset_at
    if delay_seconds <= 0:
        return {"Retry-After": "0"}

    return {"Retry-After": str(int(math.ceil(delay_seconds)))}


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
            headers = None
            if isinstance(exc, RateLimitExceededError):
                headers = _build_retry_after_header(exc.reset_at)

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
        logger.error(f"Unhandled exception: {exc}")
        logger.error(traceback.format_exc())
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
