"""Middleware that prevents backend request loops."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, status
from src.core.security.loop_prevention import LOOP_GUARD_HEADER
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response


class LoopPreventionMiddleware(BaseHTTPMiddleware):
    """Reject requests that originate from backend connectors."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.headers.get(LOOP_GUARD_HEADER):
            return JSONResponse(
                status_code=status.HTTP_508_LOOP_DETECTED,
                content={"detail": "Request loop detected"},
            )
        return await call_next(request)
