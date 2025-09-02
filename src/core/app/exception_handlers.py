from __future__ import annotations

import logging

from fastapi import Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


async def httpx_request_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle httpx connectivity errors as 503 Service Unavailable."""
    logger.error("HTTPX request error: %s", exc, exc_info=True)
    return JSONResponse(
        {
            "error": {
                "message": f"Upstream connection error: {exc}",
                "type": "UpstreamConnectionError",
            }
        },
        status_code=503,
    )


async def json_decode_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle JSON decoding errors as 400 Bad Request."""
    logger.warning("JSON decode error: %s", exc, exc_info=True)
    return JSONResponse(
        {
            "error": {
                "message": "Malformed JSON payload",
                "type": "JSONDecodeError",
            }
        },
        status_code=400,
    )


async def pydantic_validation_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Handle Pydantic validation errors as 422 Unprocessable Entity."""
    logger.warning("Validation error: %s", exc, exc_info=True)
    details = exc.errors() if isinstance(exc, ValidationError) else None
    return JSONResponse(
        {
            "error": {
                "message": "Validation failed",
                "type": "ValidationError",
                "details": details,
            }
        },
        status_code=422,
    )
