from __future__ import annotations

import logging
import math
import time
from typing import Any

from fastapi import Request
from src.core.common.exceptions import LLMProxyError, RateLimitExceededError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response


class DomainExceptionMiddleware(BaseHTTPMiddleware):
    """Translate domain exceptions to HTTP responses.

    Centralized middleware that catches project-specific exceptions
    (LLMProxyError and subclasses) and renders consistent JSON error
    payloads, while logging with appropriate severity. Unknown errors
    are mapped to HTTP 500 with a generic body to avoid leaking internals.

    Intentional behavior: keep transport concerns here so that core
    adapters/services remain domain-centric.
    """

    def __init__(self, app: Any) -> None:  # type: ignore[override]
        super().__init__(app)
        self._logger = logging.getLogger(__name__)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            return await call_next(request)
        except LLMProxyError as e:
            # 4xx -> warning; 5xx -> error
            if 400 <= int(getattr(e, "status_code", 500)) < 500:
                self._logger.warning("Domain error: %s", e, exc_info=True)
            else:
                self._logger.error("Domain error: %s", e, exc_info=True)
            content = e.to_dict()
            status_code = int(getattr(e, "status_code", 500))
            headers = _build_retry_after_header(
                getattr(e, "reset_at", None) if isinstance(e, RateLimitExceededError) else None
            )
            return JSONResponse(
                content=content, status_code=status_code, headers=headers
            )
        except Exception as e:  # Fallback for unexpected errors
            self._logger.error("Unhandled exception: %s", e, exc_info=True)
            return JSONResponse(
                content={
                    "error": {
                        "message": "Internal Server Error",
                        "type": "InternalError",
                    }
                },
                status_code=500,
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

    return {"Retry-After": str(int(math.ceil(delay_seconds)))}
