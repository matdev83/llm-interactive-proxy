from __future__ import annotations

# type: ignore[unreachable]
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException

from src.core.common.exceptions import LLMProxyError

# Import HTTP status constants
from src.core.constants import (
    HTTP_400_BAD_REQUEST_MESSAGE,
    HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
)

logger = logging.getLogger(__name__)


def _is_streaming_request(request: Request) -> bool:
    """Detect if this is a streaming request expecting SSE format.

    Args:
        request: The FastAPI request object

    Returns:
        True if the request expects streaming SSE response, False otherwise
    """
    # Check Accept header for text/event-stream
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return True

    # Check if this is a chat completions endpoint
    # Most clients don't send Accept header, so we need to check the endpoint
    if not request.url.path.endswith("/chat/completions"):
        return False

    # For chat completions, check if there's any indication of streaming
    # Note: The request body might already be consumed at this point,
    # so we check the state that might have been set earlier
    if hasattr(request.state, "is_streaming"):
        return bool(request.state.is_streaming)

    # Fallback: assume non-streaming for chat completions unless proven otherwise
    # The Accept header is the most reliable indicator
    return False


async def _generate_streaming_error_response(
    error_message: str,
    error_type: str,
    status_code: int,
    details: Any | None = None,
) -> AsyncIterator[bytes]:
    """Generate SSE-formatted error response for streaming requests.

    Args:
        error_message: The error message
        error_type: The error type/class name
        status_code: HTTP status code
        details: Optional additional error details

    Yields:
        SSE-formatted error chunks as bytes
    """
    created = int(time.time())
    error_data = {
        "id": f"chatcmpl-error-{created}",
        "object": "chat.completion.chunk",
        "created": created,
        "model": "error",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "error",
            }
        ],
        "error": {
            "message": error_message,
            "type": error_type,
            "code": "unknown",
            "retryable": False,
            "status_code": status_code,
            **({"details": details} if details else {}),
        },
    }

    # Yield error chunk as proper SSE event
    yield f"data: {json.dumps(error_data)}\n\n".encode()

    # Yield [DONE] sentinel as separate SSE event
    yield b"data: [DONE]\n\n"


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
        logger.warning("Validation error: %s", exc.errors(), exc_info=True)

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
        JSON or SSE streaming response with error details
    """
    if logger.isEnabledFor(logging.WARNING):
        logger.warning("HTTP error %s: %s", exc.status_code, exc.detail, exc_info=True)

    # Check if this is a streaming request
    is_streaming = _is_streaming_request(request)

    # Extract error information
    message, error_type, extra_details = _normalize_http_exception_detail(exc.detail)

    # Return SSE-formatted error for streaming requests
    if is_streaming:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Returning SSE-formatted error response for streaming request: %s",
                message,
            )
        return StreamingResponse(
            _generate_streaming_error_response(
                error_message=message,
                error_type=error_type,
                status_code=exc.status_code,
                details=extra_details,
            ),
            media_type="text/event-stream",
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    # Check if this is a chat completions endpoint request
    is_chat_completions = False
    if request.url.path.endswith("/chat/completions"):
        is_chat_completions = True

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
        A JSON or SSE streaming response with error details
    """
    # Be defensive: exc may not be a ProxyError here (we register this
    # handler for Exception as well). Safely extract fields when present.
    exc_name = exc.__class__.__name__
    exc_message = getattr(exc, "message", str(exc))
    exc_status = getattr(exc, "status_code", None)
    if exc_status is not None:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "%s (%s): %s", exc_name, exc_status, exc_message, exc_info=True
            )
    else:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("%s: %s", exc_name, exc_message, exc_info=True)

    # Check if this is a streaming request
    is_streaming = _is_streaming_request(request)

    # Check if this is a chat completions endpoint request
    is_chat_completions = False
    if request.url.path.endswith("/chat/completions"):
        is_chat_completions = True

    # If this is a LLMProxyError, preserve its status_code and details.
    if isinstance(exc, LLMProxyError):  # pyright: ignore[reportUnnecessaryIsInstance]
        if exc.details and logger.isEnabledFor(logging.DEBUG):
            # Use serialize_for_logging to redact any sensitive data in error details (NFR4.2)
            from src.core.common.contract_serialization import serialize_for_logging

            redacted_details = serialize_for_logging(exc.details, redact=True)
            logger.debug("Error details: %s", redacted_details)

        status_code = (
            500
            if getattr(exc, "message", None) == "all backends failed"
            else exc.status_code
        )

        # Return SSE-formatted error for streaming requests
        if is_streaming:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Returning SSE-formatted error response for streaming request: %s",
                    exc_message,
                )
            return StreamingResponse(
                _generate_streaming_error_response(
                    error_message=exc_message,
                    error_type=exc_name,
                    status_code=status_code,
                    details=getattr(exc, "details", None),
                ),
                media_type="text/event-stream",
                status_code=status_code,
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
        JSON or SSE streaming response with error details
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

    # Check if this is a streaming request
    is_streaming = _is_streaming_request(request)

    # Return SSE-formatted error for streaming requests
    if is_streaming:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Returning SSE-formatted error response for streaming unhandled exception"
            )
        return StreamingResponse(
            _generate_streaming_error_response(
                error_message=HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
                error_type="InternalError",
                status_code=500,
                details=None,
            ),
            media_type="text/event-stream",
            status_code=500,
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
