"""Interface for centralized backend work cancellation enforcement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from src.core.domain.request_context import RequestContext
from src.core.domain.session_key import SessionKey

BackendWorkPurpose = Literal[
    "primary_completion",
    "empty_stream_retry",
    "failover_attempt",
    "quality_verifier",
]


class IBackendWorkGuard(ABC):
    """Central guard for backend-producing work."""

    @abstractmethod
    def ensure_session_active(
        self,
        *,
        context: RequestContext | None,
        purpose: BackendWorkPurpose,
        require_scope: bool = True,
    ) -> SessionKey | None:
        """Resolve request scope and ensure it is not cancelled."""

    @abstractmethod
    def is_cancelled(self, session_key: SessionKey | None) -> bool:
        """Return whether a resolved scope is cancelled."""

    @abstractmethod
    def wrap_stream_with_cancellation(
        self,
        *,
        stream: AsyncIterator[Any],
        session_key: SessionKey | None,
        purpose: BackendWorkPurpose,
    ) -> AsyncIterator[Any]:
        """Wrap a stream and stop yielding when cancellation is observed."""
