from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic.types import JsonValue

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
    async def capture_inbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        request_payload: Any,
        raw_body: bytes | None = None,
    ) -> None:
        """Capture inbound request from client to proxy."""

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
        response_content: dict[str, JsonValue] | bytes | None,
    ) -> None:
        """Capture a full non-streaming inbound response.

        Args:
            context: Request context
            session_id: Session ID
            backend: Backend name
            model: Model name
            key_name: Key name for redaction
            response_content: Response content (JSON-serializable dict, bytes, or None)
        """

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
    async def capture_outbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        response_content: dict[str, JsonValue] | bytes | None,
    ) -> None:
        """Capture a full non-streaming outbound response to the client.

        Args:
            context: Request context
            session_id: Session ID
            backend: Backend name (optional)
            model: Model name (optional)
            key_name: Key name for redaction
            response_content: Response content (JSON-serializable dict, bytes, or None)
        """

    @abstractmethod
    def wrap_outbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Wrap a streaming iterator to capture bytes sent to the client."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully stop background work and flush outstanding data."""
