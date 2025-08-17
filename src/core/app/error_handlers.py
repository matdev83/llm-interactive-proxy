from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

from src.core.common.exceptions import ProxyError

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
                    "message": "Request validation error",
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
    logger.warning(f"HTTP error {exc.status_code}: {exc.detail}")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": {
                "error": {
                    "message": str(exc.detail),
                    "type": "HttpError",
                    "status_code": exc.status_code,
                }
            }
        },
        headers=getattr(exc, "headers", None),
    )


async def proxy_exception_handler(request: Request, exc: ProxyError) -> Response:
    """Handle custom proxy exceptions.

    Args:
        request: The request that caused the exception
        exc: The proxy exception

    Returns:
        JSON response with error details
    """
    logger.warning(f"{exc.__class__.__name__} ({exc.status_code}): {exc.message}")

    if exc.details and logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Error details: {exc.details}")

    return JSONResponse(
        status_code=(
            500
            if getattr(exc, "message", None) == "all backends failed"
            else exc.status_code
        ),
        content={
            "detail": {
                "error": exc.message,
                **({"details": exc.details} if getattr(exc, "details", None) else {}),
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

    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "error": {
                    "message": "Internal server error",
                    "type": "InternalError",
                    "status_code": 500,
                }
            }
        },
    )


def configure_exception_handlers(app: FastAPI) -> None:
    """Configure exception handlers for the FastAPI application.

    Args:
        app: The FastAPI application
    """
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ProxyError, proxy_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, general_exception_handler)
