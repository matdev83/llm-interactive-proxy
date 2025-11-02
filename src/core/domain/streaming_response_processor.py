"""
Streaming response processor interfaces and utilities.

This module provides interfaces and utilities for processing streaming
responses in a consistent way, regardless of the source or format.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from src.core.ports.streaming import IStreamProcessor, StreamingContent

logger = logging.getLogger(__name__)


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
    ) -> None:
        """Initialize loop detection processor.

        Args:
            loop_detector_factory: Factory function to create new loop detector instances per session.
            cancel_callback: Optional callback to trigger API cancellation when loop is detected.
        """
        self.loop_detector_factory = loop_detector_factory
        self.cancel_callback = cancel_callback
        # Per-session detector instances to ensure isolation
        self._session_detectors: dict[str, ILoopDetector] = {}

    def _get_detector_for_session(self, session_id: str) -> ILoopDetector:
        """Get or create a loop detector for the given session.

        Args:
            session_id: The session identifier

        Returns:
            A loop detector instance dedicated to this session
        """
        if session_id not in self._session_detectors:
            detector = self.loop_detector_factory()
            self._session_detectors[session_id] = detector
            logger.debug(f"Created new loop detector for session {session_id}")
        return self._session_detectors[session_id]

    def cleanup_session(self, session_id: str) -> None:
        """Clean up detector instance for a completed session.

        Args:
            session_id: The session identifier to clean up
        """
        if session_id in self._session_detectors:
            del self._session_detectors[session_id]
            logger.debug(f"Cleaned up loop detector for session {session_id}")

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

        # Prefer an explicit session identifier when provided; otherwise fall back to stream.
        raw_session = content.metadata.get("session_id") or content.metadata.get("id")
        session_id = str(raw_session) if raw_session else str(stream_id)

        # Get the detector instance for this specific session
        loop_detector = self._get_detector_for_session(session_id)

        # Process the content for loop detection
        # Ensure content is a string for loop detector
        content_str = content.content
        logger.debug(
            f"LoopDetectionProcessor processing chunk for session {session_id}: '{content_str[:50]}...' (length: {len(content_str)})"
        )
        detection_event = loop_detector.process_chunk(content_str)

        # Clean up detector when stream is done
        if content.is_done:
            self.cleanup_session(session_id)

        if detection_event:
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

            return self._create_cancellation_content(detection_event)
        else:
            # No loop detected, pass through the content
            return content

    def _create_cancellation_content(
        self, detection_event: LoopDetectionEvent
    ) -> StreamingContent:
        """Create a StreamingContent object with a cancellation message."""
        payload = (
            "[Response cancelled: Loop detected - Pattern "
            f"'{detection_event.pattern[:30]}...' repeated "
            f"{detection_event.repetition_count} times]"
        )

        return StreamingContent(
            content=payload,
            is_done=True,
            is_cancellation=True,
            metadata={
                "loop_detected": True,
                "pattern": detection_event.pattern,
                "repetition_count": detection_event.repetition_count,
            },
        )
