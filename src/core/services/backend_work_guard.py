"""Centralized backend-work cancellation guard."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.common.exceptions import LLMProxyError
from src.core.common.session_key_resolver import (
    resolve_session_key_from_request_context,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.session_key import SessionKey
from src.core.interfaces.backend_work_guard_interface import (
    BackendWorkPurpose,
    IBackendWorkGuard,
)
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)

logger = logging.getLogger(__name__)


class BackendWorkGuard(IBackendWorkGuard):
    """Default guard implementation backed by session cancellation coordinator."""

    def __init__(
        self,
        cancellation_coordinator: ISessionCancellationCoordinator | None,
        *,
        strict_http_scope: bool = True,
    ) -> None:
        self._cancellation_coordinator = cancellation_coordinator
        self._strict_http_scope = strict_http_scope

    def ensure_session_active(
        self,
        *,
        context: RequestContext | None,
        purpose: BackendWorkPurpose,
        require_scope: bool = True,
    ) -> SessionKey | None:
        session_key = resolve_session_key_from_request_context(context)
        if (
            require_scope
            and self._strict_http_scope
            and context is not None
            and session_key is None
        ):
            raise LLMProxyError(
                message="Unscoped HTTP backend work blocked (missing request_id/session scope)",
                details={
                    "purpose": purpose,
                    "request_id": getattr(context, "request_id", None),
                },
                status_code=500,
            )
        if self._cancellation_coordinator is not None and session_key is not None:
            self._cancellation_coordinator.ensure_not_cancelled(session_key)
        return session_key

    def is_cancelled(self, session_key: SessionKey | None) -> bool:
        if self._cancellation_coordinator is None or session_key is None:
            return False
        return self._cancellation_coordinator.is_cancelled(session_key)

    def wrap_stream_with_cancellation(
        self,
        *,
        stream: AsyncIterator[Any],
        session_key: SessionKey | None,
        purpose: BackendWorkPurpose,
    ) -> AsyncIterator[Any]:
        async def _guarded() -> AsyncIterator[Any]:
            if self.is_cancelled(session_key):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Stream blocked before first chunk due to cancellation",
                        extra={"purpose": purpose},
                    )
                return
            async for chunk in stream:
                if self.is_cancelled(session_key):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Stopping stream due to cancellation",
                            extra={"purpose": purpose},
                        )
                    return
                yield chunk

        return _guarded()
