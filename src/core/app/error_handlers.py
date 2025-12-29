from __future__ import annotations

# type: ignore[unreachable]
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

from src.core.common.exceptions import LLMProxyError

# Import HTTP status constants
from src.core.constants import (
    HTTP_400_BAD_REQUEST_MESSAGE,
    HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
)

logger = logging.getLogger(__name__)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """Handle FastAPI validation errors.

    Args:
        request: The request that caused the exception
        exc: The validation exception

    Returns:
        JSON response with error details
    """
    if logger.isEnabledFor(logging.WARNING):
        logger.warning("Validation error: %s", exc.errors())

    error_details: list[dict[str, Any]] = []
    for error in exc.errors():
        error_details.append(
            {
                "loc": error.get("loc", []),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
        )

    return JSONResponse(
        status_code=400,
        content={
            "detail": {
                "error": {
                    "message": HTTP_400_BAD_REQUEST_MESSAGE,
                    "type": "ValidationError",
                    "status_code": 400,
                    "details": {"errors": error_details},
                }
            }
        },
    )


def _merge_details_with_extras(
    details: Any | None,
    extras: dict[str, Any],
) -> Any | None:
    """Merge extras into details, handling various detail types."""
    if not extras:
        return details
    if details is None:
        return extras
    elif isinstance(details, Mapping):
        return {**extras, **details}
    else:
        return {"value": details, "extras": extras}


def _normalize_http_exception_detail(
    detail: Any,
) -> tuple[str, str, Any | None]:
    """Extract a stable message/type/details triple from HTTPException detail.

    Handles three cases:
    1. FastAPI-style payloads with nested "error" structure
    2. Generic mappings with message/type/details at top level
       - Extra fields are merged into details (details takes precedence)
    3. Fallback: Any non-mapping value is stringified

    Args:
        detail: The detail payload from HTTPException

    Returns:
        Tuple of (message, type, details) where extras are merged into details
    """

    default_type = "HttpError"
    if isinstance(detail, Mapping):
        # Handle FastAPI-style payloads where the detail already contains an
        # ``error`` structure with message/type/details fields.
        nested_error = detail.get("error")
        if isinstance(nested_error, Mapping):
            message = nested_error.get("message")
            error_type = nested_error.get("type", default_type)
            details = nested_error.get("details")
            extras = {k: v for k, v in detail.items() if k != "error"}
            details = _merge_details_with_extras(details, extras)
            if message is None:
                message = str({k: v for k, v in detail.items() if k != "error"})
            return str(message), str(error_type), details

        # Generic mapping: look for common keys first.
        message = detail.get("message")
        error_type = detail.get("type", default_type)
        details = detail.get("details")

        # Preserve any remaining fields as part of the details payload so that
        # callers do not lose structured context.
        extras = {
            key: value
            for key, value in detail.items()
            if key not in {"message", "type", "details"}
        }
        details = _merge_details_with_extras(details, extras)

        if message is None:
            message = str({k: v for k, v in detail.items() if k != "details"})

        return str(message), str(error_type), details

    # Fallback: treat the detail as a simple string payload.
    return str(detail), default_type, None


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Handle FastAPI HTTP exceptions.

    Args:
        request: The request that caused the exception
        exc: The HTTP exception

    Returns:
        JSON response with error details
    """
    if logger.isEnabledFor(logging.WARNING):
        logger.warning("HTTP error %s: %s", exc.status_code, exc.detail)

    # Check if this is a chat completions endpoint request
    is_chat_completions = False
    if request.url.path.endswith("/chat/completions"):
        is_chat_completions = True

    message, error_type, extra_details = _normalize_http_exception_detail(exc.detail)

    error_payload: dict[str, Any] = {
        "message": message,
        "type": error_type,
        "status_code": exc.status_code,
    }
    if extra_details is not None:
        error_payload["details"] = extra_details

    if is_chat_completions:
        # Return OpenAI-compatible error response with choices for chat completions
        import time

        content = {
            "id": f"error-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "error",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"Error: {message}",
                    },
                    "finish_reason": "error",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": error_payload,
        }
    else:
        # Standard error response for non-chat completions endpoints
        content = {
            "detail": {
                "error": error_payload,
            }
        }

    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=getattr(exc, "headers", None),
    )


async def proxy_exception_handler(request: Request, exc: LLMProxyError) -> Response:
    """Handle LLMProxyError exceptions.

    This handler provides consistent error responses for domain exceptions
    that originate within the proxy core.

    Args:
        request: The request that caused the exception
        exc: The LLMProxyError exception

    Returns:
        A JSON response with error details
    """
    # Be defensive: exc may not be a ProxyError here (we register this
    # handler for Exception as well). Safely extract fields when present.
    exc_name = exc.__class__.__name__
    exc_message = getattr(exc, "message", str(exc))
    exc_status = getattr(exc, "status_code", None)
    if exc_status is not None:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("%s (%s): %s", exc_name, exc_status, exc_message)
    else:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("%s: %s", exc_name, exc_message)

    # Check if this is a chat completions endpoint request
    is_chat_completions = False
    if request.url.path.endswith("/chat/completions"):
        is_chat_completions = True

    # If this is a LLMProxyError, preserve its status_code and details.
    if isinstance(exc, LLMProxyError):
        if exc.details and logger.isEnabledFor(logging.DEBUG):
            logger.debug("Error details: %s", exc.details)

        status_code = (
            500
            if getattr(exc, "message", None) == "all backends failed"
            else exc.status_code
        )

        if is_chat_completions:
            # Return OpenAI-compatible error response with choices for chat completions
            import time

            content = {
                "id": f"error-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "error",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Error: {exc_message}",
                        },
                        "finish_reason": "error",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "error": {
                    "message": exc_message,
                    "type": exc_name,
                    "status_code": status_code,
                    **(
                        {"details": exc.details}
                        if getattr(exc, "details", None)
                        else {}
                    ),
                },
            }
        else:
            # Standard error response for non-chat completions endpoints
            error_payload: dict[str, Any] = {
                "message": exc_message,
                "type": exc_name,
                "status_code": status_code,
            }
            if getattr(exc, "details", None):
                error_payload["details"] = exc.details

            content = {
                "detail": {
                    "error": error_payload,
                }
            }

        return JSONResponse(status_code=status_code, content=content)

    # Fallback for non-ProxyError exceptions  # type: ignore[unreachable]  # type: ignore[unreachable]
    return JSONResponse(  # type: ignore[unreachable]
        status_code=getattr(exc, "status_code", 500),
        content={
            "detail": {
                "error": {
                    "message": exc_message,
                    "type": exc_name,
                    "status_code": getattr(exc, "status_code", 500),
                }
            }
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> Response:
    """Handle all other exceptions.

    Args:
        request: The request that caused the exception
        exc: The exception

    Returns:
        JSON response with error details
    """
    # Starlette calls exception handlers after it has already unwound the stack,
    # so `sys.exc_info()` no longer contains the traceback for `exc`. Passing the
    # exception object to `exc_info` does not help either because the logging
    # module treats any non-tuple value as truthy and simply falls back to
    # `sys.exc_info()`, which results in a `(None, None, None)` triple. This
    # silently drops the traceback and makes debugging significantly harder.
    #
    # Instead, explicitly provide the exception info tuple so that the original
    # traceback attached to the exception is preserved in the logs.
    logger.exception(
        "Unhandled exception",
        exc_info=(type(exc), exc, getattr(exc, "__traceback__", None)),
    )

    # Check if this is a chat completions endpoint request
    is_chat_completions = False
    if request.url.path.endswith("/chat/completions"):
        is_chat_completions = True

    if is_chat_completions:
        # Return OpenAI-compatible error response with choices for chat completions
        import time

        content = {
            "id": f"error-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "error",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"Error: {HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE}",
                    },
                    "finish_reason": "error",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": {
                "message": HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
                "type": "InternalError",
                "status_code": 500,
            },
        }
    else:
        # Standard error response for non-chat completions endpoints
        content = {
            "detail": {
                "error": {
                    "message": HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
                    "type": "InternalError",
                    "status_code": 500,
                }
            }
        }

    return JSONResponse(status_code=500, content=content)


def configure_exception_handlers(app: FastAPI) -> None:
    """Configure exception handlers for the FastAPI application.

    Args:
        app: The FastAPI application
    """
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(LLMProxyError, proxy_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, general_exception_handler)
