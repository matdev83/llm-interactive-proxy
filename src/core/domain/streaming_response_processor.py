"""
Streaming response processor interfaces and utilities.

This module provides interfaces and utilities for processing streaming
responses in a consistent way, regardless of the source or format.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

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
        self.loop_detector = loop_detector

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
        detection_event = self.loop_detector.process_chunk(content_str)

        if detection_event:
            logger.warning(
                f"Loop detected in streaming response by LoopDetectionProcessor: {detection_event.pattern[:50]}..."
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
