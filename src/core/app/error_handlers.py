from __future__ import annotations

# type: ignore[unreachable]
import logging
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
        logger.warning(f"Validation error: {exc.errors()}")

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


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Handle FastAPI HTTP exceptions.

    Args:
        request: The request that caused the exception
        exc: The HTTP exception

    Returns:
        JSON response with error details
    """
    if logger.isEnabledFor(logging.WARNING):
        logger.warning(f"HTTP error {exc.status_code}: {exc.detail}")

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
                        "content": f"Error: {exc.detail!s}",
                    },
                    "finish_reason": "error",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": {
                "message": str(exc.detail),
                "type": "HttpError",
                "status_code": exc.status_code,
            },
        }
    else:
        # Standard error response for non-chat completions endpoints
        content = {
            "detail": {
                "error": {
                    "message": str(exc.detail),
                    "type": "HttpError",
                    "status_code": exc.status_code,
                }
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
            logger.warning(f"{exc_name} ({exc_status}): {exc_message}")
    else:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"{exc_name}: {exc_message}")

    # Check if this is a chat completions endpoint request
    is_chat_completions = False
    if request.url.path.endswith("/chat/completions"):
        is_chat_completions = True

    # If this is a LLMProxyError, preserve its status_code and details.
    if isinstance(exc, LLMProxyError):
        if exc.details and logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Error details: {exc.details}")

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
            content = {
                "detail": {
                    "error": exc_message,
                    **(
                        {"details": exc.details}
                        if getattr(exc, "details", None)
                        else {}
                    ),
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
    logger.exception("Unhandled exception", exc_info=exc)

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
