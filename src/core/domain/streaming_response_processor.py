"""
Streaming response processor interfaces and utilities.

This module provides interfaces and utilities for processing streaming
responses in a consistent way, regardless of the source or format.
"""

from __future__ import annotations

import copy
import logging
from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


# The StreamingContent class definition has been moved to src/core/domain/streaming_content.py


class IStreamProcessor(ABC):
    """Interface for processing streaming content."""

    @abstractmethod
    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process a streaming content chunk.

        Args:
            content: The content to process

        Returns:
            The processed content
        """


from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.loop_detection.event import LoopDetectionEvent


class LoopDetectionProcessor(IStreamProcessor):
    """Stream processor that checks for repetitive patterns in the content.

    This implementation uses a hash-based loop detection mechanism.
    """

    def __init__(self, loop_detector: ILoopDetector) -> None:
        """Initialize the loop detection processor.

        Args:
            loop_detector: The loop detector instance to use.
        """
        self._base_detector = loop_detector
        self._stream_detectors: dict[str, ILoopDetector] = {}

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process a streaming content chunk and check for loops.

        Args:
            content: The content to process.

        Returns:
            The processed content, potentially with a cancellation message
            if a loop is detected.
        """
        if content.is_empty and not content.is_done:
            return content

        # Process the content for loop detection
        # Ensure content is a string for the loop detector
        content_str = content.content
        stream_id = self._extract_stream_id(content)
        detector = self._get_detector_for_stream(stream_id)
        detection_event = detector.process_chunk(content_str)

        if detection_event:
            logger.warning(
                f"Loop detected in streaming response by LoopDetectionProcessor: {detection_event.pattern[:50]}..."
            )
            self._cleanup_stream_detector(stream_id)
            return self._create_cancellation_content(detection_event)

        if content.is_done or content.is_cancellation:
            self._cleanup_stream_detector(stream_id)

        # No loop detected, pass through the content
        return content

    def reset(self) -> None:
        """Reset cached detector state for all active streams."""

        self._stream_detectors.clear()
        self._reset_detector(self._base_detector)

    def _extract_stream_id(self, content: StreamingContent) -> str | None:
        metadata: dict[str, Any] = content.metadata if isinstance(content.metadata, dict) else {}
        stream_id = metadata.get("stream_id")
        if stream_id is None:
            return None
        return str(stream_id)

    def _get_detector_for_stream(self, stream_id: str | None) -> ILoopDetector:
        if not stream_id:
            return self._base_detector

        detector = self._stream_detectors.get(stream_id)
        if detector is None:
            detector = self._clone_base_detector()
            self._stream_detectors[stream_id] = detector
        return detector

    def _clone_base_detector(self) -> ILoopDetector:
        try:
            clone = copy.deepcopy(self._base_detector)
        except Exception:
            logger.warning(
                "Falling back to shared loop detector instance; could not isolate stream state",
                exc_info=True,
            )
            clone = self._base_detector

        self._reset_detector(clone)
        return clone

    def _cleanup_stream_detector(self, stream_id: str | None) -> None:
        if not stream_id:
            self._reset_detector(self._base_detector)
            return

        detector = self._stream_detectors.pop(stream_id, None)
        if detector is not None:
            self._reset_detector(detector)

    @staticmethod
    def _reset_detector(detector: ILoopDetector) -> None:
        reset = getattr(detector, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                logger.debug("Failed to reset loop detector instance", exc_info=True)

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
