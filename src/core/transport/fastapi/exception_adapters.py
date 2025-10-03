"""
FastAPI exception adapters.

This module contains adapters for converting domain exceptions
to FastAPI/Starlette HTTP exceptions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status

from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    InvalidRequestError,
    LLMProxyError,
    LoopDetectionError,
    RateLimitExceededError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)


def map_domain_exception_to_http_exception(exc: LLMProxyError) -> HTTPException:
    """Map a domain exception to a FastAPI HTTP exception.

    Args:
        exc: The domain exception to map

    Returns:
        A FastAPI HTTP exception
    """
    # If the exception already has a status code, use it
    status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
    headers: dict[str, str] | None = None

    # Map specific exception types to specific status codes
    if isinstance(exc, AuthenticationError):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, ConfigurationError | InvalidRequestError):
        status_code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, ServiceUnavailableError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, BackendError):
        # Preserve specific BackendError subclasses' status_code if provided
        explicit = getattr(exc, "status_code", None)
        if (
            isinstance(explicit, int)
            and explicit != status.HTTP_500_INTERNAL_SERVER_ERROR
        ):
            status_code = explicit
        else:
            status_code = status.HTTP_502_BAD_GATEWAY
    elif isinstance(exc, RateLimitExceededError):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
        if exc.reset_at is not None:
            headers = {"Retry-After": str(exc.reset_at)}
    elif isinstance(exc, LoopDetectionError):
        status_code = status.HTTP_400_BAD_REQUEST

    # Convert exception details to a dict for the response
    detail: str | dict[str, Any] = (
        str(exc.message) if hasattr(exc, "message") else str(exc)
    )

    # If the exception has additional details, include them
    if hasattr(exc, "to_dict"):
        dict_result = exc.to_dict()
        # If to_dict() returns {"error": {...}}, unwrap it for HTTPException detail
        if isinstance(dict_result, dict) and "error" in dict_result:
            detail = dict_result["error"]
        else:
            detail = dict_result
    elif hasattr(exc, "details") and exc.details:
        if isinstance(detail, str):
            detail = {"message": detail, "details": exc.details}
        elif isinstance(detail, dict):
            detail["details"] = exc.details

    # Create and return the HTTP exception
    return HTTPException(status_code=status_code, detail=detail, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers for domain exceptions in a FastAPI app.

    Args:
        app: The FastAPI application to register handlers for
    """

    # Create a generic exception handler that maps domain exceptions to HTTP responses
    async def domain_exception_handler(
        request: Request, exc: LLMProxyError
    ) -> Response:
        http_exception = map_domain_exception_to_http_exception(exc)
        return Response(
            content=json.dumps(http_exception.detail),
            status_code=http_exception.status_code,
            media_type="application/json",
            headers=getattr(http_exception, "headers", None),
        )

    # Register for all domain exception types
    app.exception_handler(LLMProxyError)(domain_exception_handler)
    app.exception_handler(AuthenticationError)(domain_exception_handler)
    app.exception_handler(BackendError)(domain_exception_handler)
    app.exception_handler(ConfigurationError)(domain_exception_handler)
    app.exception_handler(InvalidRequestError)(domain_exception_handler)
    app.exception_handler(LoopDetectionError)(domain_exception_handler)
    app.exception_handler(RateLimitExceededError)(domain_exception_handler)
    app.exception_handler(ServiceUnavailableError)(domain_exception_handler)

    # Register a generic exception handler for unhandled exceptions
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> Response:
        # Don't handle HTTPException, let FastAPI handle it
        if isinstance(exc, HTTPException):
            raise exc

        # Log the exception
        if logger.isEnabledFor(logging.ERROR):
            logger.error(f"Unhandled exception: {exc}", exc_info=True)

        # Return a 500 error
        return Response(
            content=json.dumps(
                {
                    "error": {
                        "message": "An unexpected error occurred",
                        "type": "server_error",
                    }
                }
            ),
            status_code=500,
            media_type="application/json",
        )
