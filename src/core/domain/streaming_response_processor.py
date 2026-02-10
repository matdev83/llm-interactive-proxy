"""
Streaming response processor interfaces and utilities.

This module provides interfaces and utilities for processing streaming
responses in a consistent way, regardless of the source or format.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent

logger = logging.getLogger(__name__)

_SSE_PREFIXES = ("event:", "data:")


from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.services.streaming.stream_utils import get_stream_id as _get_stream_id
from src.loop_detection.event import LoopDetectionEvent


class LoopDetectionProcessor(IStreamProcessor):
    """Stream processor that checks for repetitive patterns in the content and handles API cancellation.

    This implementation uses a hash-based loop detection mechanism and integrates
    with the backend's cancellation system to properly break loops with token waste prevention.

    IMPORTANT: This processor maintains per-session detector instances to ensure that
    loop detection state is never shared between different sessions.
    """

    def __init__(
        self,
        loop_detector_factory: Callable[[], ILoopDetector],
        cancel_callback: Callable[[], Awaitable[None]] | None = None,
        *,
        min_chunks_before_detection: int = 2,
        max_active_sessions: int = 1000,
    ) -> None:
        """Initialize loop detection processor.

        Args:
            loop_detector_factory: Factory function to create new loop detector instances per session.
            cancel_callback: Optional callback to trigger API cancellation when loop is detected.
            max_active_sessions: Maximum number of active sessions to track (LRU eviction).
        """
        self.loop_detector_factory = loop_detector_factory
        self.cancel_callback = cancel_callback
        # Per-session detector instances to ensure isolation
        self._session_detectors: OrderedDict[str, ILoopDetector] = OrderedDict()
        # Track sessions that have already triggered cancellation to suppress duplicates
        self._cancelled_sessions: set[str] = set()
        self._stream_chunk_counts: dict[str, int] = {}
        self._min_chunks_before_detection = max(1, min_chunks_before_detection)
        self._max_active_sessions = max_active_sessions

    def _get_detector_for_session(self, session_id: str) -> ILoopDetector:
        """Get or create a loop detector for the given session.

        Args:
            session_id: The session identifier

        Returns:
            A loop detector instance dedicated to this session
        """
        if session_id in self._session_detectors:
            self._session_detectors.move_to_end(session_id)
            return self._session_detectors[session_id]

        if len(self._session_detectors) >= self._max_active_sessions:
            # Evict oldest session (FIFO from OrderedDict)
            oldest_session = next(iter(self._session_detectors))
            self.cleanup_session(oldest_session)
            logger.warning(
                f"Evicted stale loop detector for session {oldest_session} due to capacity limit"
            )

        detector = self.loop_detector_factory()
        self._session_detectors[session_id] = detector
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Created new loop detector for session %s", session_id)
        return detector

    def cleanup_session(self, session_id: str) -> None:
        """Clean up detector instance for a completed session.

        Args:
            session_id: The session identifier to clean up
        """
        if session_id in self._session_detectors:
            del self._session_detectors[session_id]
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Cleaned up loop detector for session %s", session_id)
        self._cancelled_sessions.discard(session_id)
        self._stream_chunk_counts.pop(session_id, None)

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process a streaming content chunk and check for loops.

        Args:
            content: The content to process.

        Returns:
            The processed content, with API cancellation if a loop is detected.
        """
        if content.is_empty and not content.is_done:
            return content

        # Ensure a stable stream identifier so metadata stays consistent across processors.
        stream_id = _get_stream_id(content)

        metadata = content.metadata or {}
        if (
            (isinstance(metadata.get("tool_calls"), list) and metadata["tool_calls"])
            or metadata.get("finish_reason") == "tool_calls"
            or metadata.get("role") == "tool"
        ):
            return content

        # Prefer an explicit session identifier when provided; otherwise fall back to stream.
        raw_session = content.metadata.get("session_id") or content.metadata.get("id")
        session_id = str(raw_session) if raw_session else str(stream_id)
        chunk_count = self._stream_chunk_counts.get(session_id, 0) + 1
        self._stream_chunk_counts[session_id] = chunk_count

        if session_id in self._cancelled_sessions:
            if content.is_done:
                self.cleanup_session(session_id)
                self._cancelled_sessions.discard(session_id)
                return self._create_cancellation_content(
                    detection_event=None, session_id=session_id
                )
            # Suppress further chunks after cancellation for this session/stream.
            return self._create_cancellation_content(
                detection_event=None, session_id=session_id
            )

        # Get the detector instance for this specific session
        loop_detector = self._get_detector_for_session(session_id)

        # Process loop detection using visible textual payload only.
        # This avoids false positives on repeated metadata-only JSON chunks.
        content_str = self._extract_loop_detection_text(content.content)
        if not content_str:
            if content.is_done:
                self.cleanup_session(session_id)
            return content

        stripped_content = content_str.lstrip()

        if stripped_content.startswith(_SSE_PREFIXES):
            if content.is_done:
                self.cleanup_session(session_id)
            return content

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                f"LoopDetectionProcessor processing chunk for session {session_id}: '{content_str[:50]}...' (length: {len(content_str)})",
            )
        detection_event = loop_detector.process_chunk(content_str)

        # Clean up detector when stream is done
        if content.is_done:
            self.cleanup_session(session_id)

        if detection_event:
            if chunk_count < self._min_chunks_before_detection and not content.is_done:
                logger.debug(
                    "Suppressing loop detection for session %s until minimum chunk count reached (%s < %s)",
                    session_id,
                    chunk_count,
                    self._min_chunks_before_detection,
                )
                return content

            logger.warning(
                "Loop detected in streaming response by LoopDetectionProcessor: pattern='%s...', repetitions=%s, total_length=%s",
                detection_event.pattern[:50],
                detection_event.repetition_count,
                detection_event.total_length,
            )

            # Trigger API cancellation if callback is available
            if self.cancel_callback is not None:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Triggering API cancellation due to loop detection: pattern='%s', repetitions=%s",
                        detection_event.pattern[:50],
                        detection_event.repetition_count,
                    )
                try:
                    await self.cancel_callback()
                except Exception as e:
                    logger.error(
                        f"Failed to trigger API cancellation: {e}", exc_info=True
                    )

            self._cancelled_sessions.add(session_id)
            return self._create_cancellation_content(
                detection_event, session_id=session_id
            )
        else:
            # No loop detected, pass through the content
            return content

    def _extract_loop_detection_text(self, content_value: Any) -> str:
        """Extract user-visible text from streaming chunks for loop detection."""
        if isinstance(content_value, bytes):
            try:
                return content_value.decode("utf-8")
            except UnicodeDecodeError:
                return content_value.decode("latin-1", errors="ignore")

        if isinstance(content_value, dict):
            visible_from_choices = self._extract_visible_text_from_choices(
                content_value
            )
            if visible_from_choices is not None:
                return visible_from_choices

            for key in ("content", "text"):
                normalized = self._normalize_text_field(content_value.get(key))
                if normalized:
                    return normalized

            # Metadata-only payloads should not drive loop detection.
            return ""

        if content_value is None:
            return ""

        return str(content_value)

    def _extract_visible_text_from_choices(self, payload: dict[str, Any]) -> str | None:
        """Extract visible content from OpenAI-style choices payloads.

        Returns:
            A string (possibly empty) when the payload is OpenAI-style.
            None when payload does not contain a choices list.
        """
        choices = payload.get("choices")
        if not isinstance(choices, list):
            return None

        text_parts: list[str] = []
        has_choice_blocks = False

        for choice in choices:
            if not isinstance(choice, dict):
                continue

            block = choice.get("delta")
            if not isinstance(block, dict):
                block = choice.get("message")
            if not isinstance(block, dict):
                continue

            has_choice_blocks = True
            normalized = self._normalize_text_field(block.get("content"))
            if normalized:
                text_parts.append(normalized)

        if text_parts:
            return "".join(text_parts)
        if has_choice_blocks:
            return ""
        return None

    def _normalize_text_field(self, value: Any) -> str:
        """Normalize content/text fields that may be strings or content-part lists."""
        if isinstance(value, str):
            return value

        if not isinstance(value, list):
            return ""

        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value:
                parts.append(text_value)

        return "".join(parts)

    def _create_cancellation_content(
        self, detection_event: LoopDetectionEvent | None, session_id: str
    ) -> StreamingContent:
        """Create a StreamingContent cancellation marker without leaking debug text."""

        metadata: dict[str, Any] = {"loop_detected": True, "session_id": session_id}
        if detection_event:
            metadata.update(
                {
                    "pattern": detection_event.pattern,
                    "repetition_count": detection_event.repetition_count,
                    "total_length": detection_event.total_length,
                }
            )

        return StreamingContent(
            content="",
            is_done=True,
            is_cancellation=True,
            metadata=metadata,
        )
