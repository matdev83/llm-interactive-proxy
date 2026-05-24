from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic.types import JsonValue

from src.core.domain.request_context import RequestContext
from src.core.domain.usage_canonical_record import CanonicalUsageRecord


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
        capture_metadata: dict[str, JsonValue] | None = None,
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
        capture_metadata: dict[str, JsonValue] | None = None,
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
        canonical_usage: CanonicalUsageRecord | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture a full non-streaming inbound response.

        Args:
            context: Request context
            session_id: Session ID
            backend: Backend name
            model: Model name
            key_name: Key name for redaction
            response_content: Response content (JSON-serializable dict, bytes, or None)
            canonical_usage: Optional canonical usage record
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
        capture_metadata: dict[str, JsonValue] | None = None,
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
        capture_metadata: dict[str, JsonValue] | None = None,
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
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> AsyncIterator[bytes]:
        """Wrap a streaming iterator to capture bytes sent to the client."""

    @abstractmethod
    async def capture_stream_completion(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        eos_metadata: dict[str, JsonValue] | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture canonical usage for a completed streaming response.

        This method is called after a streaming response completes and canonical
        usage has been built. It attaches canonical_usage to the stream_end entry
        that was created when the stream ended.

        Args:
            context: Request context
            session_id: Session ID
            backend: Backend name
            model: Model name
            key_name: Key name for redaction
            canonical_usage: Optional canonical usage record
            eos_metadata: Optional End-of-Session metadata dict (JSON-serializable values only)
                with keys: eos (bool), eos_signal (str), eos_reason (str),
                eos_termination_category (str), eos_error_classification (str),
                eos_error_status_code (int)
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully stop background work and flush outstanding data."""
