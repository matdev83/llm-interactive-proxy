"""
Main loop detection logic.

This module provides the LoopDetector class which manages response buffers,
analyzes patterns, and determines when to trigger loop detection events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .analyzer import LoopDetectionEvent, PatternAnalyzer
from .buffer import ResponseBuffer
from .config import LoopDetectionConfig
from .hasher import ContentHasher

logger = logging.getLogger(__name__)


class LoopDetector:
    """Main loop detection class."""

    def __init__(
        self,
        config: LoopDetectionConfig | None = None,
        on_loop_detected: Callable[[LoopDetectionEvent], None] | None = None,
    ):
        self.config = config or LoopDetectionConfig()
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

        # Analyze for loops using the new PatternAnalyzer
        event = self.analyzer.analyze_chunk(chunk, self.buffer.get_content())
        if event is not None:
            # Update state to avoid retriggering immediately
            self.last_detection_position = self.total_processed
            self._last_analysis_position = self.total_processed
            # Trigger callback if provided
            if self.on_loop_detected:
                try:
                    self.on_loop_detected(event)
                except Exception as e:
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error("Error in loop detection callback: %s", e)
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

    def update_config(self, new_config: LoopDetectionConfig) -> None:
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

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Loop detector configuration updated: enabled=%s", self.is_active
            )
