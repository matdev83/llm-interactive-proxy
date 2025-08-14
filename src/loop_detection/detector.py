"""
Main loop detection logic.

This module provides the LoopDetector class which manages response buffers,
analyzes patterns, and determines when to trigger loop detection events.
"""

from __future__ import annotations

import hashlib
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from .config import LoopDetectionConfig

logger = logging.getLogger(__name__)


@dataclass
class LoopDetectionEvent:
    """Event triggered when a loop is detected."""

    pattern: str
    repetition_count: int
    total_length: int
    confidence: float
    buffer_content: str
    timestamp: float


class ResponseBuffer:
    """Manages a sliding window buffer of response content."""

    def __init__(self, max_size: int = 2048):
        self.max_size = max_size
        self.buffer: deque[str] = deque(maxlen=max_size)
        self.total_length = 0
        # Track actual stored content length for proper sliding window behavior
        self.stored_length = 0

    def append(self, text: str) -> None:
        """Append text to the buffer.

        Stores text chunks instead of individual characters for better performance.
        Manages sliding window behavior manually to maintain exact size limits.
        """
        if not text:
            return

        text_len = len(text)

        # If adding this text would exceed max_size, remove old content first
        if self.stored_length + text_len > self.max_size:
            # Remove old chunks until we have enough space
            excess = self.stored_length + text_len - self.max_size
            while excess > 0 and self.buffer:
                old_chunk = self.buffer.popleft()
                old_len = len(old_chunk)
                self.stored_length -= old_len
                excess -= old_len

        # Add the new text chunk
        self.buffer.append(text)
        self.stored_length += text_len
        self.total_length += text_len

    def get_content(self) -> str:
        """Get the current buffer content as a string."""
        return "".join(self.buffer)

    def get_recent_content(self, length: int) -> str:
        """Get the most recent content up to specified length."""
        content = self.get_content()
        return content[-length:] if len(content) > length else content

    def clear(self) -> None:
        """Clear the buffer."""
        self.buffer.clear()
        self.total_length = 0
        self.stored_length = 0

    def size(self) -> int:
        """Get current buffer size."""
        return self.stored_length


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

        # Fast hash-chunk algorithm state (ported from gemini-cli)
        self._stream_history: str = ""
        self._content_stats: dict[str, list[int]] = {}
        self._last_chunk_index: int = 0
        self._in_code_block: bool = False

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

        # Fast path: hash-chunk analysis inspired by gemini-cli
        event = self._process_fast_hash_chunk_path(chunk)
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

    def _process_fast_hash_chunk_path(
        self, new_content: str
    ) -> LoopDetectionEvent | None:
        """Process new content using the fast hash-chunk algorithm.

        Ported from gemini-cli LoopDetectionService.checkContentLoop/analyzeContentChunksForLoop.
        """
        # Detect and handle code fences to avoid false positives in code blocks
        num_fences = new_content.count("```")
        if num_fences:
            self._reset_fast_path_content_tracking(reset_history=True)
        if num_fences % 2 == 1:
            # Toggle code block state
            self._in_code_block = not self._in_code_block
        if self._in_code_block:
            return None

        # Append, then truncate and update indices if needed
        self._stream_history += new_content
        self._truncate_and_update_indices()

        chunk_size = max(1, int(getattr(self.config, "content_chunk_size", 50)))
        loop_threshold = max(2, int(getattr(self.config, "content_loop_threshold", 10)))

        # Slide a window and evaluate each chunk
        while self._has_more_chunks_to_process(chunk_size):
            end_index = self._last_chunk_index + chunk_size
            current_chunk = self._stream_history[self._last_chunk_index : end_index]
            chunk_hash = hashlib.sha256(current_chunk.encode("utf-8")).hexdigest()

            if self._is_loop_detected_for_chunk(
                current_chunk, chunk_hash, chunk_size, loop_threshold
            ):
                # Build an event compatible with existing interface
                buffer_content = self.buffer.get_content()
                return self._create_detection_event_from_chunk(
                    pattern=current_chunk,
                    repetition_count=loop_threshold,
                    total_length=chunk_size * loop_threshold,
                    confidence=1.0,
                    buffer_content=buffer_content,
                )

            self._last_chunk_index += 1

        return None

    def _truncate_and_update_indices(self) -> None:
        max_history = int(getattr(self.config, "max_history_length", 1000))
        if len(self._stream_history) <= max_history:
            return
        trunc_amount = len(self._stream_history) - max_history
        self._stream_history = self._stream_history[trunc_amount:]
        self._last_chunk_index = max(0, self._last_chunk_index - trunc_amount)
        new_stats: dict[str, list[int]] = {}
        for h, indices in self._content_stats.items():
            adjusted = [
                idx - trunc_amount for idx in indices if idx - trunc_amount >= 0
            ]
            if adjusted:
                new_stats[h] = adjusted
        self._content_stats = new_stats

    def _has_more_chunks_to_process(self, chunk_size: int) -> bool:
        return self._last_chunk_index + chunk_size <= len(self._stream_history)

    def _is_loop_detected_for_chunk(
        self,
        chunk: str,
        hash_hex: str,
        chunk_size: int,
        loop_threshold: int,
    ) -> bool:
        existing_indices = self._content_stats.get(hash_hex)
        if not existing_indices:
            self._content_stats[hash_hex] = [self._last_chunk_index]
            return False

        # Verify actual content equality to guard against hash collisions
        first_index = existing_indices[0]
        original_chunk = self._stream_history[first_index : first_index + chunk_size]
        if original_chunk != chunk:
            return False

        existing_indices.append(self._last_chunk_index)
        if len(existing_indices) < loop_threshold:
            return False

        recent = existing_indices[-loop_threshold:]
        total_distance = recent[-1] - recent[0]
        average_distance = total_distance / (loop_threshold - 1)
        max_allowed_distance = chunk_size * 1.5
        return average_distance <= max_allowed_distance

    def _create_detection_event_from_chunk(
        self,
        *,
        pattern: str,
        repetition_count: int,
        total_length: int,
        confidence: float,
        buffer_content: str,
    ) -> LoopDetectionEvent:
        """Create a loop detection event for the current chunk pattern."""
        import time

        return LoopDetectionEvent(
            pattern=pattern,
            repetition_count=repetition_count,
            total_length=total_length,
            confidence=confidence,
            buffer_content=buffer_content,
            timestamp=time.time(),
        )

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
        # Reset fast path state
        self._reset_fast_path_content_tracking(reset_history=True)
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
        # Reset fast-path indices but keep history consistent with buffer reset
        self._reset_fast_path_content_tracking(reset_history=True)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Loop detector configuration updated: enabled=%s", self.is_active
            )

    def _reset_fast_path_content_tracking(self, *, reset_history: bool) -> None:
        if reset_history:
            self._stream_history = ""
        self._content_stats = {}
        self._last_chunk_index = 0
        self._in_code_block = False
