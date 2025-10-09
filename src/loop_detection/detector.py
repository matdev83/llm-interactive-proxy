"""
Main loop detection logic.

This module provides the LoopDetector class which manages response buffers,
analyzes patterns, and determines when to trigger loop detection events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.core.interfaces.loop_detector_interface import ILoopDetector

if TYPE_CHECKING:
    from src.core.interfaces.loop_detector_interface import LoopDetectionResult
from src.loop_detection.event import (
    LoopDetectionEvent,  # Added import for return type annotation
)

from .analyzer import PatternAnalyzer
from .buffer import ResponseBuffer
from .config import InternalLoopDetectionConfig

# from .event import LoopDetectionEvent # Already imported above
from .hasher import ContentHasher

logger = logging.getLogger(__name__)


class LoopDetector(ILoopDetector):
    """Main loop detection class."""

    def __init__(
        self,
        config: InternalLoopDetectionConfig | None = None,
        on_loop_detected: Callable[[LoopDetectionEvent], None] | None = None,
    ):
        self.config = config or InternalLoopDetectionConfig()
        self.on_loop_detected = on_loop_detected

        # Validate configuration
        config_errors = self.config.validate()
        if config_errors:
            raise ValueError(
                f"Invalid loop detection configuration: {', '.join(config_errors)}"
            )

        # Initialize components
        self.buffer = ResponseBuffer(max_size=self.config.buffer_size)
        self.hasher = ContentHasher()
        self.analyzer = PatternAnalyzer(self.config, self.hasher)

        # State tracking
        self.is_active = self.config.enabled
        self.total_processed = 0
        self.last_detection_position = -1
        self._history: list[LoopDetectionEvent] = []
        # Track the last position (character count) where heavy analysis was
        # performed so we can skip redundant work when only a few new
        # characters have arrived (important for token-by-token streaming).
        self._last_analysis_position = -1

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "LoopDetector initialized: enabled=%s, buffer_size=%s, max_pattern_length=%s",
                self.is_active,
                self.config.buffer_size,
                self.config.max_pattern_length,
            )

    def process_chunk(self, chunk: str) -> LoopDetectionEvent | None:
        """Process a chunk of response text and check for loops."""
        if not self.is_active or not chunk:
            return None

        chunk_len = len(chunk)

        # Add chunk to buffer
        self.buffer.append(chunk)
        self.total_processed += chunk_len

        # Respect the configured analysis interval to avoid redundant heavy checks.
        if self.config.analysis_interval > 0 and self._last_analysis_position >= 0:
            processed_since_last = self.total_processed - self._last_analysis_position
            if processed_since_last < self.config.analysis_interval:
                return None

        # Analyze for loops using the new PatternAnalyzer
        event = self.analyzer.analyze_chunk(chunk, self.buffer.get_content())
        self._last_analysis_position = self.total_processed
        if event is not None:
            # Update state to avoid retriggering immediately
            self.last_detection_position = self.total_processed
            self._history.append(event)
            # Trigger callback if provided
            if self.on_loop_detected:
                try:
                    self.on_loop_detected(event)
                except Exception as e:
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            "Error in loop detection callback: %s", e, exc_info=True
                        )
            return event

        # No detection
        return None

    def enable(self) -> None:
        """Enable loop detection."""
        self.is_active = True
        if logger.isEnabledFor(logging.INFO):
            logger.info("Loop detection enabled")

    def disable(self) -> None:
        """Disable loop detection."""
        self.is_active = False
        if logger.isEnabledFor(logging.INFO):
            logger.info("Loop detection disabled")

    def is_enabled(self) -> bool:
        """Check if loop detection is enabled."""
        return self.is_active

    def reset(self) -> None:
        """Reset the detector state."""
        self.buffer.clear()
        self.total_processed = 0
        self.last_detection_position = -1
        self._last_analysis_position = -1
        self.analyzer.reset()  # Reset the analyzer's state
        self._history.clear()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Loop detector state reset")

    def get_stats(self) -> dict:
        """Get detector statistics."""
        # These should never be None after initialization
        assert self.config.short_pattern_threshold is not None
        assert self.config.medium_pattern_threshold is not None
        assert self.config.long_pattern_threshold is not None

        return {
            "is_active": self.is_active,
            "last_detection_position": self.last_detection_position,
            "config": {
                "buffer_size": self.config.buffer_size,
                "max_pattern_length": self.config.max_pattern_length,
                "short_threshold": {
                    "min_repetitions": self.config.short_pattern_threshold.min_repetitions,
                    "min_total_length": self.config.short_pattern_threshold.min_total_length,
                },
                "medium_threshold": {
                    "min_repetitions": self.config.medium_pattern_threshold.min_repetitions,
                    "min_total_length": self.config.medium_pattern_threshold.min_total_length,
                },
                "long_threshold": {
                    "min_repetitions": self.config.long_pattern_threshold.min_repetitions,
                    "min_total_length": self.config.long_pattern_threshold.min_total_length,
                },
            },
        }

    def get_loop_history(self) -> list[LoopDetectionEvent]:
        """Retrieve the aggregated history of detected loops."""
        return self._history.copy()

    def get_current_state(self) -> dict[str, Any]:
        """
        Retrieves the current internal state of the loop detector.
        """
        return {
            "buffer_content_length": len(self.buffer.get_content()),
            "total_processed": self.total_processed,
            "last_detection_position": self.last_detection_position,
            "analyzer_state": self.analyzer.get_state(),
        }

    def update_config(self, new_config: InternalLoopDetectionConfig) -> None:
        """Update the detector configuration."""
        # Validate new configuration
        config_errors = new_config.validate()
        if config_errors:
            raise ValueError(
                f"Invalid loop detection configuration: {', '.join(config_errors)}"
            )

        self.config = new_config
        self.is_active = new_config.enabled

        # Update components
        if self.buffer.max_size != new_config.buffer_size:
            # Create new buffer with new size
            old_content = self.buffer.get_content()
            self.buffer = ResponseBuffer(max_size=new_config.buffer_size)
            if old_content:
                # Keep the most recent content that fits
                recent_content = (
                    old_content[-new_config.buffer_size :]
                    if len(old_content) > new_config.buffer_size
                    else old_content
                )
                self.buffer.append(recent_content)

        # Force re-analysis after configuration changes
        self._last_analysis_position = -1
        self.analyzer.config = new_config  # Update analyzer with new config
        self.analyzer.reset()  # Reset analyzer state due to config change
        self._history.clear()

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        """Async interface required by ILoopDetector to check the entire content.

        This uses the existing analyzer on the full content string and returns a
        LoopDetectionResult compatible object.
        """
        from src.core.interfaces.loop_detector_interface import LoopDetectionResult

        if not content:
            return LoopDetectionResult(has_loop=False)

        # Use a clean analyzer snapshot so non-streaming checks don't disturb
        # ongoing streaming state maintained by process_chunk.
        analyzer_state = self.analyzer.snapshot_state()
        try:
            self.analyzer.reset()
            event = self.analyzer.analyze_chunk(content, content)
        finally:
            self.analyzer.restore_state(analyzer_state)
        if event is None:
            return LoopDetectionResult(has_loop=False)

        repetition_count = event.repetition_count

        # Record detection without mutating the restored streaming analyzer state.
        self._history.append(event)

        pattern_length = 0
        if repetition_count > 0 and event.total_length > 0:
            if event.total_length % repetition_count == 0:
                pattern_length = event.total_length // repetition_count
            elif event.pattern:
                pattern_length = len(event.pattern)
        elif event.pattern:
            pattern_length = len(event.pattern)

        return LoopDetectionResult(
            has_loop=True,
            pattern=event.pattern,
            repetitions=repetition_count,
            details={
                "pattern_length": pattern_length,
                "total_repeated_chars": event.total_length,
                "repetitions": repetition_count,
            },
        )
