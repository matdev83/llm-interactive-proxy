"""Empty response recovery helper.

This module restores the retry steering behaviour that existed before the
RequestContext refactor.  The helper delegates to the empty-response middleware
so tests and integrations that relied on the recovery class keep working while
the actual logic stays centralized.
"""

from __future__ import annotations

from typing import Any

from src.core.config.app_config import AppConfig
from src.core.services.empty_response_middleware import (
    EmptyResponseMiddleware,
    EmptyResponseRetryError,
)


class EmptyResponseRecovery:
    """Adapter around :class:`EmptyResponseMiddleware` for legacy imports."""

    def __init__(self, config: AppConfig | None = None) -> None:
        cfg = config or AppConfig()
        self._middleware = EmptyResponseMiddleware(
            enabled=getattr(cfg.empty_response, "enabled", True),
            max_retries=getattr(cfg.empty_response, "max_retries", 1),
        )

    async def retry_if_needed(
        self,
        context: Any,
        request: Any,
        response: Any,
    ) -> Any:
        """Inspect the response and perform steering retries when required."""

        middleware_context = {
            "original_request": request,
            "backend_response": response,
        }

        try:
            processed = await self._middleware.process(
                response=response,
                session_id=getattr(context, "session_id", "unknown"),
                context=middleware_context,
                is_streaming=getattr(request, "stream", False),
            )
            return processed
        except EmptyResponseRetryError:
            return None
