"""End-of-Session stream processor.

This processor detects completion markers in streaming content and emits
End-of-Session signals via the EndOfSessionService.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, cast

from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.interfaces.end_of_session_service_interface import IEndOfSessionService
from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent

logger = logging.getLogger(__name__)


class EndOfSessionStreamProcessor(IStreamProcessor):
    """Stream processor that detects completion markers and emits EoS signals.

    This processor observes StreamingContent for completion markers such as:
    - `[DONE]` sentinel in content
    - `finish_reason` in metadata (except "tool_calls")
    - `message_stop` in metadata
    - `response.completed` in metadata
    - `is_done=True` flag (except when finish_reason="tool_calls")

    Note: finish_reason="tool_calls" indicates a mid-session pause for tool
    execution, not session termination. The session continues after the client
    sends tool results back.

    When a completion marker is detected, it emits an End-of-Session signal
    via the EndOfSessionService. The processor preserves content unchanged
    (pass-through behavior).
    """

    def __init__(
        self,
        end_of_session_service: IEndOfSessionService,
        config: EndOfSessionConfig,
    ) -> None:
        """Initialize the End-of-Session stream processor.

        Args:
            end_of_session_service: Service for recording EoS signals
            config: End-of-Session configuration
        """
        self._eos_service = end_of_session_service
        self._config = config

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process streaming content and detect completion markers.

        Args:
            content: The streaming content to process

        Returns:
            The content unchanged (pass-through processor)
        """
        # Skip if EoS detection is disabled
        if not self._config.enabled or not self._config.detect_stream_signals:
            return content

        # Extract session_id from metadata
        session_id = self._extract_session_id(content)
        if not session_id:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS stream processor: Missing session_id in metadata, skipping emission",
                    extra={"stream_id": content.stream_id},
                )
            return content

        # Early exit if session has already ended (hot-path dedupe)
        if await self._eos_service.has_ended(
            session_id, content.metadata.get("request_id") if content.metadata else None
        ):
            return content

        # Detect completion markers
        signal = self._detect_completion_signal(content, session_id)
        if signal is None:
            return content

        # Emit signal (fail-open on errors)
        try:
            await self._eos_service.record_signal(signal)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to record EoS signal from stream processor: %s",
                    e,
                    exc_info=True,
                    extra={
                        "session_id": session_id,
                        "signal_type": signal.signal_type.value,
                    },
                )

        return content

    def _extract_session_id(self, content: StreamingContent) -> str | None:
        """Extract session_id from StreamingContent metadata.

        Args:
            content: Streaming content with metadata

        Returns:
            Session ID if found, None otherwise
        """
        metadata = content.metadata or {}
        session_id = metadata.get("session_id") or metadata.get("id")
        return str(session_id) if session_id else None

    def _detect_completion_signal(
        self, content: StreamingContent, session_id: str
    ) -> EndOfSessionSignal | None:
        """Detect completion markers and create EoS signal.

        Args:
            content: Streaming content to check
            session_id: Session identifier

        Returns:
            EndOfSessionSignal if completion detected, None otherwise
        """
        metadata = content.metadata or {}

        # Check for is_done flag, but skip tool_calls (mid-session pause, not termination)
        if content.is_done:
            # Skip EoS emission for tool calls - session continues after tool execution
            finish_reason = metadata.get("finish_reason")

            # Also check finish_reason in content dict if present
            if finish_reason is None and isinstance(content.content, dict):
                finish_reason = content.content.get("finish_reason")

            if finish_reason == "tool_calls":
                return None

            return EndOfSessionSignal(
                session_id=session_id,
                signal_type=EndOfSessionSignalType.DONE_SENTINEL,
                termination_category=EndOfSessionTerminationCategory.NORMAL,
                observed_at=datetime.now(timezone.utc),
                reason="Stream completed (is_done=True)",
                protocol=metadata.get("protocol"),
                request_id=metadata.get("request_id"),
                backend=metadata.get("backend_name") or metadata.get("backend"),
            )

        # Check for [DONE] sentinel in content
        content_str = ""
        if isinstance(content.content, str):
            content_str = content.content
        elif isinstance(content.content, bytes):
            content_str = content.content.decode("utf-8", errors="ignore")
        else:
            # Check in nested content fields (must be dict if not str or bytes)
            content_val = cast(dict[str, Any], content.content)
            content_str = str(content_val.get("content", ""))

        if "[DONE]" in content_str:
            return EndOfSessionSignal(
                session_id=session_id,
                signal_type=EndOfSessionSignalType.DONE_SENTINEL,
                termination_category=EndOfSessionTerminationCategory.NORMAL,
                observed_at=datetime.now(timezone.utc),
                reason="Stream completion sentinel [DONE] detected",
                protocol=metadata.get("protocol"),
                request_id=metadata.get("request_id"),
                backend=metadata.get("backend_name") or metadata.get("backend"),
            )

        # Check for finish_reason in metadata
        finish_reason = metadata.get("finish_reason")
        if finish_reason:
            # Skip EoS emission for tool calls - session continues after tool execution
            if finish_reason == "tool_calls":
                return None

            return EndOfSessionSignal(
                session_id=session_id,
                signal_type=EndOfSessionSignalType.FINISH_REASON,
                termination_category=EndOfSessionTerminationCategory.NORMAL,
                observed_at=datetime.now(timezone.utc),
                reason=f"Finish reason: {finish_reason}",
                protocol=metadata.get("protocol"),
                request_id=metadata.get("request_id"),
                backend=metadata.get("backend_name") or metadata.get("backend"),
            )

        # Check for message_stop in metadata
        if metadata.get("message_stop"):
            return EndOfSessionSignal(
                session_id=session_id,
                signal_type=EndOfSessionSignalType.RESPONSE_COMPLETED,
                termination_category=EndOfSessionTerminationCategory.NORMAL,
                observed_at=datetime.now(timezone.utc),
                reason="Message stop marker detected",
                protocol=metadata.get("protocol"),
                request_id=metadata.get("request_id"),
                backend=metadata.get("backend_name") or metadata.get("backend"),
            )

        # Check for response.completed in metadata
        if metadata.get("response.completed") or metadata.get("response_completed"):
            return EndOfSessionSignal(
                session_id=session_id,
                signal_type=EndOfSessionSignalType.RESPONSE_COMPLETED,
                termination_category=EndOfSessionTerminationCategory.NORMAL,
                observed_at=datetime.now(timezone.utc),
                reason="Response completion event detected",
                protocol=metadata.get("protocol"),
                request_id=metadata.get("request_id"),
                backend=metadata.get("backend_name") or metadata.get("backend"),
            )

        return None

    def reset(self) -> None:
        """Reset processor state for new stream.

        This processor is stateless, so reset is a no-op.
        """
