"""
Streaming response processor interfaces and utilities.

This module provides interfaces and utilities for processing streaming
responses in a consistent way, regardless of the source or format.
"""

from __future__ import annotations

import json
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
        logger.debug(f"Created new loop detector for session {session_id}")
        return detector

    def cleanup_session(self, session_id: str) -> None:
        """Clean up detector instance for a completed session.

        Args:
            session_id: The session identifier to clean up
        """
        if session_id in self._session_detectors:
            del self._session_detectors[session_id]
            logger.debug(f"Cleaned up loop detector for session {session_id}")
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

        # Process the content for loop detection
        # Ensure content is a string for loop detector
        content_value = content.content
        if isinstance(content_value, bytes):
            try:
                content_str = content_value.decode("utf-8")
            except UnicodeDecodeError:
                content_str = content_value.decode("latin-1", errors="ignore")
        elif isinstance(content_value, dict):
            # Use dict() to safely handle StopChunkWithUsage which is a dict
            # subclass that raises an error on str()
            content_str = json.dumps(dict(content_value))
        else:
            content_str = str(content_value or "")
        stripped_content = content_str.lstrip()

        if stripped_content.startswith(_SSE_PREFIXES):
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
                f"Loop detected in streaming response by LoopDetectionProcessor: pattern='{detection_event.pattern[:50]}...', "
                f"repetitions={detection_event.repetition_count}, total_length={detection_event.total_length}"
            )

            # Trigger API cancellation if callback is available
            if self.cancel_callback is not None:
                logger.info(
                    f"Triggering API cancellation due to loop detection: pattern='{detection_event.pattern[:50]}', repetitions={detection_event.repetition_count}"
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
