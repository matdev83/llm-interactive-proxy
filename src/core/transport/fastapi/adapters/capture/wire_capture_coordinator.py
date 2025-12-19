"""Wire capture coordination for response adapters."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.wire_capture_interface import IWireCapture

if TYPE_CHECKING:
    from src.core.domain.request_context import RequestContext

logger = logging.getLogger(__name__)


class WireCaptureCoordinator:
    """Coordinate wire capture operations for responses.

    Extracts metadata from envelopes and coordinates background capture
    tasks for non-streaming responses and stream wrapping for streaming responses.
    """

    def __init__(self, wire_capture: IWireCapture | None = None) -> None:
        """Initialize wire capture coordinator.

        Args:
            wire_capture: Optional IWireCapture instance. If None, operations are no-ops.
        """
        self._wire_capture = wire_capture

    def schedule_capture(
        self,
        envelope: ResponseEnvelope,
        response_content: Any,
        context: RequestContext | None = None,
    ) -> None:
        """Schedule async capture for non-streaming response.

        Args:
            envelope: Response envelope
            response_content: Response content to capture
            context: Optional request context
        """
        if self._wire_capture is None or not self._wire_capture.enabled():
            return

        backend, model, key_name, session_id = self._infer_capture_fields(
            envelope, context
        )
        session_value = self._resolve_capture_session_id(session_id, context)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running, cannot schedule task
            return

        task = loop.create_task(
            self._wire_capture.capture_outbound_response(
                context=context,
                session_id=session_value,
                backend=backend,
                model=model,
                key_name=key_name,
                response_content=response_content,
            )
        )
        # Ensure task is stored and handle exceptions to avoid "not awaited" warnings
        task.add_done_callback(lambda t: t.exception())

    def wrap_stream(
        self,
        envelope: StreamingResponseEnvelope,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Wrap stream for capture if enabled.

        Args:
            envelope: Streaming response envelope
            stream: Stream iterator to wrap
            context: Optional request context

        Yields:
            Stream chunks (potentially captured)
        """
        if self._wire_capture is None or not self._wire_capture.enabled():
            return stream

        # Extract context from envelope if available, or use None
        context = getattr(envelope, "context", None)

        backend, model, key_name, session_id = self._infer_capture_fields(
            envelope, context
        )
        session_value = self._resolve_capture_session_id(session_id, context)

        return self._wire_capture.wrap_outbound_stream(
            context=context,
            session_id=session_value,
            backend=backend,
            model=model,
            key_name=key_name,
            stream=stream,
        )

    def _infer_capture_fields(
        self, envelope: Any, context: RequestContext | None
    ) -> tuple[str, str, str | None, str | None]:
        """Extract backend/model/key and session identifiers for capture.

        Args:
            envelope: Response envelope
            context: Optional request context

        Returns:
            Tuple of (backend, model, key_name, session_id)
        """
        backend = "proxy"
        model = "unknown"
        key_name: str | None = None
        session_id: str | None = None

        metadata = getattr(envelope, "metadata", None)
        if isinstance(metadata, dict):
            backend = str(metadata.get("backend", backend) or backend)
            model = str(metadata.get("model", model) or model)
            key_name_candidate = metadata.get("key_name")
            if isinstance(key_name_candidate, str) and key_name_candidate.strip():
                key_name = key_name_candidate
            session_candidate = metadata.get("session_id") or metadata.get("stream_id")
            if isinstance(session_candidate, str) and session_candidate.strip():
                session_id = session_candidate

        if context is not None:
            ctx_session = getattr(context, "session_id", None)
            if isinstance(ctx_session, str) and ctx_session.strip():
                session_id = ctx_session

        return backend, model, key_name, session_id

    def _resolve_capture_session_id(
        self, session_id: str | None, context: RequestContext | None
    ) -> str | None:
        """Resolve session identifier with fallbacks to request_id.

        Args:
            session_id: Session ID from metadata
            context: Optional request context

        Returns:
            Resolved session ID or None
        """
        if session_id and str(session_id).strip():
            return str(session_id)
        if context is None:
            return None
        request_id = getattr(context, "request_id", None)
        if isinstance(request_id, str) and request_id.strip():
            return request_id
        return None
