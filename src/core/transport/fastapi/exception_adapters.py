"""
FastAPI exception adapters.

This module contains adapters for converting domain exceptions
to FastAPI/Starlette HTTP exceptions.
"""

from __future__ import annotations

import json
import logging
import math
import time
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
    RoutingError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

_ROUTING_PROTOCOL_DEFAULT = "frontend_default"
_ROUTING_PROTOCOL_MESSAGES = "frontend_messages"
_ROUTING_PROTOCOL_GENERATE = "frontend_generate"


def _detect_protocol(request: Request | None) -> str:
    """Infer frontend protocol from request path."""
    if request is None:
        return _ROUTING_PROTOCOL_DEFAULT

    path = request.url.path.lower()
    if path.startswith(("/anthropic/", "/v1/messages")):
        return _ROUTING_PROTOCOL_MESSAGES
    if path.startswith("/v1beta/"):
        return _ROUTING_PROTOCOL_GENERATE
    return _ROUTING_PROTOCOL_DEFAULT


def _infer_routing_code_from_status(status_code: int) -> str:
    if status_code == status.HTTP_404_NOT_FOUND:
        return "unknown_model"
    if status_code == status.HTTP_400_BAD_REQUEST:
        return "unsupported_on_instance"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "policy_rejected"
    return "temporarily_unavailable"


def _gemini_status_name(status_code: int) -> str:
    mapping = {
        status.HTTP_400_BAD_REQUEST: "INVALID_ARGUMENT",
        status.HTTP_401_UNAUTHORIZED: "UNAUTHENTICATED",
        status.HTTP_403_FORBIDDEN: "PERMISSION_DENIED",
        status.HTTP_404_NOT_FOUND: "NOT_FOUND",
        status.HTTP_409_CONFLICT: "ABORTED",
        status.HTTP_429_TOO_MANY_REQUESTS: "RESOURCE_EXHAUSTED",
        status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL",
        status.HTTP_503_SERVICE_UNAVAILABLE: "UNAVAILABLE",
    }
    return mapping.get(status_code, "UNKNOWN")


def _build_canonical_routing_envelope(
    exc: RoutingError, status_code: int
) -> dict[str, Any]:
    details_obj = getattr(exc, "details", None)
    details_dict = dict(details_obj) if isinstance(details_obj, dict) else {}

    code_obj = details_dict.get("code")
    code = (
        code_obj
        if isinstance(code_obj, str) and code_obj
        else _infer_routing_code_from_status(status_code)
    )

    category_obj = details_dict.get("category")
    if isinstance(category_obj, str) and category_obj:
        category = category_obj
    elif code == "unknown_model":
        category = "validation"
    elif code == "policy_rejected":
        category = "policy"
    else:
        category = "availability"

    retryable_obj = details_dict.get("retryable")
    retryable = (
        retryable_obj
        if isinstance(retryable_obj, bool)
        else code == "temporarily_unavailable"
    )

    canonical_details = dict(details_dict)
    canonical_details["code"] = code
    canonical_details["category"] = category
    canonical_details["retryable"] = retryable

    return {
        "code": code,
        "category": category,
        "retryable": retryable,
        "message": str(getattr(exc, "message", str(exc))),
        "details": canonical_details,
    }


def _map_routing_error_detail_for_protocol(
    *,
    protocol: str,
    envelope: dict[str, Any],
    status_code: int,
) -> dict[str, Any]:
    details = envelope["details"]
    message = str(envelope["message"])

    if protocol == _ROUTING_PROTOCOL_MESSAGES:
        return {
            "type": "error",
            "error": {
                "type": "routing_error",
                "message": message,
                "details": envelope,
            },
            "details": details,
        }

    if protocol == _ROUTING_PROTOCOL_GENERATE:
        return {
            "error": {
                "code": status_code,
                "message": message,
                "status": _gemini_status_name(status_code),
                "details": envelope,
            },
            "details": details,
        }

    # OpenAI-compatible default.
    return {
        "message": message,
        "type": "RoutingError",
        "details": details,
        "error": {
            "message": message,
            "type": "routing_error",
            "details": envelope,
        },
    }


def _build_retry_after_header(reset_at: float | None) -> dict[str, str] | None:
    """Compute a standards-compliant Retry-After header value."""

    if reset_at is None:
        return None

    now = time.time()
    if reset_at > now:
        delay_seconds = reset_at - now
    else:
        delay_seconds = 0

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


def map_domain_exception_to_http_exception(
    exc: LLMProxyError,
    *,
    request: Request | None = None,
) -> HTTPException:
    """Map a domain exception to a FastAPI HTTP exception.

    Args:
        exc: The domain exception to map

    Returns:
        A FastAPI HTTP exception
    """
    # If the exception already has a status code, use it
    status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)

    headers = _resolve_retry_after_header(exc)

    # Map specific exception types to specific status codes
    if isinstance(exc, AuthenticationError):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, ConfigurationError):
        status_code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, InvalidRequestError):
        # Preserve specific InvalidRequestError status_code if provided (e.g., 422)
        explicit = getattr(exc, "status_code", None)
        if (
            isinstance(explicit, int)
            and explicit != status.HTTP_500_INTERNAL_SERVER_ERROR
        ):
            status_code = explicit
        else:
            status_code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, ServiceUnavailableError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, RateLimitExceededError):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
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
    elif isinstance(exc, LoopDetectionError):
        status_code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, RoutingError):
        details_obj = getattr(exc, "details", None) or {}
        if isinstance(details_obj, dict):
            details_code = details_obj.get("code")
            if details_code == "unknown_model":
                status_code = status.HTTP_404_NOT_FOUND
            elif details_code == "unsupported_on_instance":
                status_code = status.HTTP_400_BAD_REQUEST
            elif details_code == "temporarily_unavailable":
                status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            elif details_code == "policy_rejected":
                status_code = status.HTTP_403_FORBIDDEN

        envelope = _build_canonical_routing_envelope(exc, status_code)
        routing_detail = _map_routing_error_detail_for_protocol(
            protocol=_detect_protocol(request),
            envelope=envelope,
            status_code=status_code,
        )
        return HTTPException(
            status_code=status_code,
            detail=routing_detail,
            headers=headers,
        )

    # Convert exception details to a dict for the response
    detail: str | dict[str, Any] = (
        str(exc.message) if hasattr(exc, "message") else str(exc)
    )

    # If the exception has additional details, include them
    if hasattr(exc, "to_dict"):
        dict_result = exc.to_dict()
        # If to_dict() returns {"error": {...}}, unwrap it for HTTPException detail
        detail = dict_result.get("error", dict_result)
    elif hasattr(exc, "details") and exc.details:
        detail = {"message": str(detail), "details": exc.details}

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
        http_exception = map_domain_exception_to_http_exception(exc, request=request)
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
    app.exception_handler(RoutingError)(domain_exception_handler)
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

    _ = generic_exception_handler
