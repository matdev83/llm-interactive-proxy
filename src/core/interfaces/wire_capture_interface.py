from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.request_context import RequestContext


class IWireCapture(ABC):
    """Interface for wire-level capture of LLM traffic.

    Implementations are responsible for writing captured content to a
    configured sink (e.g., a file). Methods are no-ops when capture is
    disabled, allowing callers to remain agnostic to capture enablement.
    """

    @abstractmethod
    def enabled(self) -> bool:
        """Return True if capture is enabled.

        Implementations should use application configuration to decide.
        """

    @abstractmethod
    async def capture_outbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        request_payload: Any,
    ) -> None:
        """Capture the outbound request payload before sending to backend."""

    @abstractmethod
    async def capture_inbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        response_content: Any,
    ) -> None:
        """Capture a full non-streaming inbound response."""

    @abstractmethod
    def wrap_inbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Wrap a streaming iterator to tee all bytes to the capture sink."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully stop background work and flush outstanding data."""
