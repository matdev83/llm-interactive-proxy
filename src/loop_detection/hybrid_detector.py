"""
Hybrid loop detection combining gemini-cli algorithm with efficient long pattern detection.

This detector uses:
1. Gemini-CLI algorithm for short patterns (<=50 chars) - proven and fast
2. Rolling hash algorithm for longer patterns (>50 chars) - lightweight and efficient

The design prioritizes performance since this runs on ALL proxy responses.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from src.core.interfaces.loop_detector_interface import (
    ILoopDetector,
    LoopDetectionResult,
)
from src.loop_detection.event import LoopDetectionEvent
from src.loop_detection.token_window_loop_detector import TokenWindowLoopDetector
from src.loop_detection.types import (
    HybridDetectorInternalState,
    HybridDetectorState,
    HybridDetectorStats,
    LongDetectorStats,
)

logger = logging.getLogger(__name__)

# Rolling hash parameters (optimized for performance)
HASH_BASE = 31  # Prime number for rolling hash
HASH_MOD = 2**32 - 1  # Large prime for hash space
MIN_LONG_PATTERN_LENGTH = 60  # Minimum length to consider as "long pattern"
MAX_LONG_PATTERN_LENGTH = 500  # Maximum pattern length to check (performance limit)
LONG_PATTERN_MIN_REPETITIONS = 3  # Fewer repetitions needed for long patterns
MAX_ROLLING_HISTORY = 2000  # Maximum content to keep for rolling hash analysis


@dataclass(frozen=True)
class LongPatternMatch:
    """Result of a long pattern match detection."""

    pattern: str
    repetitions: int

    def __iter__(self):
        """Allow unpacking for backward compatibility."""
        yield self.pattern
        yield self.repetitions


class RollingHashTracker:
    """
    Efficient rolling hash implementation for detecting repeated substrings.

    Uses Rabin-Karp rolling hash for O(1) hash updates and O(n) pattern detection.
    Optimized for performance - only tracks promising patterns.
    """

    def __init__(
        self,
        min_pattern_length: int = MIN_LONG_PATTERN_LENGTH,
        max_pattern_length: int = MAX_LONG_PATTERN_LENGTH,
        min_repetitions: int = LONG_PATTERN_MIN_REPETITIONS,
        max_history: int = MAX_ROLLING_HISTORY,
    ):
        self.min_pattern_length = min_pattern_length
        self.max_pattern_length = max_pattern_length
        self.min_repetitions = min_repetitions
        self.max_history = max_history

        # Content tracking
        self.content = ""
        self.pattern_candidates: dict[int, dict[int, list[int]]] = (
            {}
        )  # {hash: {length: [positions]}}
        self._last_check_length = 0

        # Performance optimization: precompute powers
        self._powers = [1]
        for _ in range(1, max_pattern_length + 1):
            self._powers.append((self._powers[-1] * HASH_BASE) % HASH_MOD)

    def add_content(self, new_content: str) -> LongPatternMatch | None:
        """
        Add new content and check for long pattern repetitions.

        Returns:
            LongPatternMatch if a loop is detected, None otherwise
        """
        if not new_content:
            return None

        self.content += new_content

        # Truncate if too long (performance optimization)
        if len(self.content) > self.max_history:
            truncate_amount = len(self.content) - self.max_history
            self.content = self.content[truncate_amount:]
            self._adjust_positions_after_truncation(truncate_amount)
            self._last_check_length = max(0, self._last_check_length - truncate_amount)

        # Only analyze if we have enough content
        content_length = len(self.content)
        if content_length < self.min_pattern_length * self.min_repetitions:
            return None

        if not self._should_run_long_detection(content_length):
            return None

        self._last_check_length = content_length

        # Check for patterns of various lengths
        # Start with longer patterns first (more specific)
        for pattern_length in range(
            min(self.max_pattern_length, content_length // self.min_repetitions),
            self.min_pattern_length - 1,
            -1,
        ):
            result = self._check_pattern_length(pattern_length)
            if result:
                return result

        return None

    def _check_pattern_length(self, pattern_length: int) -> LongPatternMatch | None:
        """Check for repeated patterns of a specific length."""
        if len(self.content) < pattern_length * self.min_repetitions:
            return None

        # Rolling hash for this pattern length
        hash_positions: dict[int, list[int]] = {}

        # Calculate initial hash for the first window
        current_hash = 0
        for i in range(pattern_length):
            current_hash = (current_hash * HASH_BASE + ord(self.content[i])) % HASH_MOD

        hash_positions[current_hash] = [0]

        # Roll the hash through the content
        for i in range(1, len(self.content) - pattern_length + 1):
            # Remove the leftmost character and add the rightmost character
            old_char = ord(self.content[i - 1])
            new_char = ord(self.content[i + pattern_length - 1])

            current_hash = (
                current_hash - old_char * self._powers[pattern_length - 1]
            ) % HASH_MOD
            current_hash = (current_hash * HASH_BASE + new_char) % HASH_MOD

            if current_hash not in hash_positions:
                hash_positions[current_hash] = []
            hash_positions[current_hash].append(i)

        # Check for repetitions
        for _hash_val, positions in hash_positions.items():
            filtered_positions = self._verify_pattern_match(positions, pattern_length)
            if filtered_positions is not None:
                # Verify actual content matches (avoid hash collisions)
                pattern = self.content[
                    filtered_positions[0] : filtered_positions[0] + pattern_length
                ]
                return LongPatternMatch(pattern=pattern, repetitions=len(filtered_positions))

        return None

    def _verify_pattern_match(
        self, positions: list[int], pattern_length: int
    ) -> list[int] | None:
        """Verify matching positions and filter out overlapping occurrences."""
        if len(positions) < self.min_repetitions:
            return None

        reference_pattern = self.content[positions[0] : positions[0] + pattern_length]
        distinct_positions = [positions[0]]

        for pos in positions[1:]:
            if pos + pattern_length > len(self.content):
                continue
            if self.content[pos : pos + pattern_length] != reference_pattern:
                continue

            # Only count non-overlapping occurrences. Require at least pattern_length
            # characters between consecutive matches to avoid counting sliding-window
            # overlaps (e.g. when the pattern itself contains smaller repetitions).
            if pos - distinct_positions[-1] < pattern_length:
                continue

            distinct_positions.append(pos)

        if len(distinct_positions) < self.min_repetitions:
            return None

        span = distinct_positions[-1] - distinct_positions[0]
        if span > pattern_length * len(distinct_positions) * 2:
            return None

        return distinct_positions

    def _adjust_positions_after_truncation(self, truncate_amount: int) -> None:
        """Adjust stored positions after content truncation."""
        # Clear pattern candidates as positions are no longer valid
        # This is simpler and safer than trying to adjust all positions
        self.pattern_candidates.clear()

    def _should_run_long_detection(self, content_length: int) -> bool:
        """
        Decide whether to run the expensive long-pattern scan.

        The scan is throttled based on how much new content has arrived since the
        previous check to avoid O(n^2) work on every tiny chunk when streaming.
        """
        if self._last_check_length == 0:
            return True

        interval = self._compute_check_interval(content_length)
        return (content_length - self._last_check_length) >= interval

    def _compute_check_interval(self, content_length: int) -> int:
        """
        Compute how many new characters should arrive before the next long scan.

        - For short buffers (<= ~2 * min loop length), we keep the interval small to
          ensure fast detection.
        - For larger buffers we scale the interval with content length to cap the
          number of full scans while keeping at least a couple of scans per window.
        """
        small_buffer_limit = self.min_pattern_length * self.min_repetitions * 2
        if content_length <= small_buffer_limit:
            return self.min_pattern_length

        dynamic_interval = max(self.min_pattern_length * 2, content_length // 3)
        max_interval = max(self.min_pattern_length * 2, self.max_history // 2)
        return min(dynamic_interval, max_interval)

    def reset(self) -> None:
        """Reset all tracking state."""
        self.content = ""
        self.pattern_candidates.clear()
        self._last_check_length = 0


class HybridLoopDetector(ILoopDetector):
    """
    Hybrid loop detector combining gemini-cli (short patterns) with rolling hash (long patterns).

    This detector is optimized for performance while providing comprehensive loop detection:
    - Short patterns (<=50 chars): Uses proven gemini-cli algorithm
    - Long patterns (>50 chars): Uses efficient rolling hash algorithm
    """

    def __init__(
        self,
        short_detector_config: dict[str, Any] | None = None,
        long_detector_config: dict[str, Any] | None = None,
    ):
        """
        Initialize hybrid detector.

        Args:
            short_detector_config: Configuration for gemini-cli detector
            long_detector_config: Configuration for rolling hash detector
        """
        # Initialize short pattern detector (gemini-cli)
        short_config = short_detector_config or {}
        self.short_detector = TokenWindowLoopDetector(
            content_loop_threshold=short_config.get("content_loop_threshold", 10),
            content_chunk_size=short_config.get("content_chunk_size", 50),
            max_history_length=short_config.get("max_history_length", 1000),
        )

        # Initialize long pattern detector (rolling hash)
        long_config = long_detector_config or {}
        self.long_detector = RollingHashTracker(
            min_pattern_length=long_config.get(
                "min_pattern_length", MIN_LONG_PATTERN_LENGTH
            ),
            max_pattern_length=long_config.get(
                "max_pattern_length", MAX_LONG_PATTERN_LENGTH
            ),
            min_repetitions=long_config.get(
                "min_repetitions", LONG_PATTERN_MIN_REPETITIONS
            ),
            max_history=long_config.get("max_history", MAX_ROLLING_HISTORY),
        )

        # State tracking
        self._is_enabled = True
        self._loop_events: list[LoopDetectionEvent] = []
        # Maximum number of loop events to keep (prevents memory leaks)
        self._max_event_history = 100

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "HybridLoopDetector initialized: short_chunk_size=%d, long_min_length=%d",
                self.short_detector.content_chunk_size,
                self.long_detector.min_pattern_length,
            )

    def process_chunk(self, chunk: str) -> LoopDetectionEvent | None:
        """
        Process a chunk of content using both short and long pattern detection.

        Args:
            chunk: Content chunk to process

        Returns:
            LoopDetectionEvent if a loop is detected, None otherwise
        """
        if not self._is_enabled or not chunk:
            return None

        # Check short patterns first (faster, more common)
        short_event = self.short_detector.process_chunk(chunk)
        if short_event:
            self._loop_events.append(short_event)
            self._truncate_event_history_if_needed()
            return short_event

        # Check long patterns (only if short patterns didn't trigger)
        long_match = self.long_detector.add_content(chunk)
        if long_match:
            pattern = long_match.pattern
            repetitions = long_match.repetitions
            pattern_length = len(pattern)
            display_pattern = (
                pattern
                if pattern_length <= 100
                else f"Long pattern detected: {pattern[:100]}..."
            )
            event = LoopDetectionEvent(
                pattern=display_pattern,
                pattern_length=pattern_length,
                repetition_count=repetitions,
                total_length=pattern_length * repetitions,
                confidence=1.0,
                buffer_content=self.long_detector.content[-200:],  # Last 200 chars
                timestamp=time.time(),
            )
            self._loop_events.append(event)
            self._truncate_event_history_if_needed()
            return event

            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Long pattern loop detected: %d repetitions of %d-char pattern",
                    repetitions,
                    pattern_length,
                )

            return event

        return None

    def _truncate_event_history_if_needed(self) -> None:
        """Truncate event history if it exceeds maximum size to prevent memory leaks.

        Uses a reasonable default limit for event history (100 events) to prevent
        unbounded growth in long-running sessions. Each event can contain large
        buffer_content strings, so limiting the number of events is important.
        """
        # Use a reasonable default limit for event history
        # This is separate from max_history_length which is for stream characters
        max_event_history = self._max_event_history

        if len(self._loop_events) <= max_event_history:
            return

        # Remove oldest entries to keep only the most recent ones
        trunc_amount = len(self._loop_events) - max_event_history
        self._loop_events = self._loop_events[trunc_amount:]

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Truncated hybrid detector event history: removed %d oldest entries, keeping %d",
                trunc_amount,
                max_event_history,
            )

    # ILoopDetector interface implementation

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        """
        Check the entire content for loops (non-streaming interface).

        Args:
            content: Full content to check

        Returns:
            LoopDetectionResult with detection status and details
        """
        if not content:
            return LoopDetectionResult(has_loop=False)

        # Save current state
        original_state = self._save_state()

        try:
            # Reset and process the content in streaming-sized slices
            self.reset()
            chunk_span = 1
            event: LoopDetectionEvent | None = None
            for index in range(0, len(content), chunk_span):
                chunk_slice = content[index : index + chunk_span]
                event = self.process_chunk(chunk_slice)
                if event:
                    break

            if event is None:
                event = self._detect_simple_repeat_loop(content)

            if event is None:
                return LoopDetectionResult(has_loop=False)

            repetition_count = event.repetition_count
            if repetition_count > 0 and event.total_length % repetition_count == 0:
                pattern_length = event.total_length // repetition_count
            else:
                pattern_length = len(event.pattern)

            short_chunk_size = self.short_detector.content_chunk_size
            if pattern_length <= short_chunk_size:
                detection_method = "short_pattern"
            else:
                detection_method = "long_pattern"

            return LoopDetectionResult(
                has_loop=True,
                pattern=event.pattern,
                repetitions=repetition_count,
                details={
                    "pattern_length": pattern_length,
                    "total_repeated_chars": event.total_length,
                    "detection_method": detection_method,
                },
            )
        finally:
            # Restore state
            self._restore_state(original_state)

    def _detect_simple_repeat_loop(self, content: str) -> LoopDetectionEvent | None:
        """Fallback detection for perfectly repeated short patterns."""
        normalized = content
        if not normalized:
            return None

        max_pattern_length = min(len(normalized) // 2, 200)
        for pattern_length in range(5, max_pattern_length + 1):
            if len(normalized) % pattern_length != 0:
                continue
            repetitions = len(normalized) // pattern_length
            if repetitions < 3:
                continue

            pattern = normalized[:pattern_length]
            if pattern * repetitions == normalized:
                event = LoopDetectionEvent(
                    pattern=pattern,
                    pattern_length=pattern_length,
                    repetition_count=repetitions,
                    total_length=pattern_length * repetitions,
                    confidence=0.75,
                    buffer_content=normalized[-200:],
                    timestamp=time.time(),
                )
                self._loop_events.append(event)
                self._truncate_event_history_if_needed()
                return event

        return None

    def enable(self) -> None:
        """Enable loop detection."""
        self._is_enabled = True
        self.short_detector.enable()
        if logger.isEnabledFor(logging.INFO):
            logger.info("Hybrid loop detection enabled")

    def disable(self) -> None:
        """Disable loop detection."""
        self._is_enabled = False
        self.short_detector.disable()
        if logger.isEnabledFor(logging.INFO):
            logger.info("Hybrid loop detection disabled")

    def is_enabled(self) -> bool:
        """Check if loop detection is enabled."""
        return self._is_enabled

    def reset(self) -> None:
        """Reset all loop detection state."""
        self.short_detector.reset()
        self.long_detector.reset()
        self._loop_events.clear()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Hybrid loop detector state reset")

    def get_stats(self) -> HybridDetectorStats:
        """Get detector statistics."""
        short_stats = self.short_detector.get_stats()
        return HybridDetectorStats(
            is_enabled=self._is_enabled,
            detection_method="hybrid",
            short_detector=short_stats,
            long_detector=LongDetectorStats(
                content_length=len(self.long_detector.content),
                min_pattern_length=self.long_detector.min_pattern_length,
                max_pattern_length=self.long_detector.max_pattern_length,
                min_repetitions=self.long_detector.min_repetitions,
            ),
            total_events=len(self._loop_events),
        )

    def get_loop_history(self) -> list[LoopDetectionEvent]:
        """Get history of detected loops."""
        return self._loop_events.copy()

    def get_current_state(self) -> HybridDetectorState:
        """Get current internal state."""
        return HybridDetectorState(
            short_detector_state=self.short_detector.get_current_state(),
            long_detector_content_length=len(self.long_detector.content),
            total_events=len(self._loop_events),
        )

    def update_config(self, new_config: Any) -> None:
        """
        Update detector configuration.

        Args:
            new_config: New configuration (dict or config object)
        """
        if isinstance(new_config, dict):
            if "short_detector" in new_config:
                self.short_detector.update_config(new_config["short_detector"])
            if "long_detector" in new_config:
                long_config = new_config["long_detector"]
                self.long_detector = RollingHashTracker(
                    min_pattern_length=long_config.get(
                        "min_pattern_length", MIN_LONG_PATTERN_LENGTH
                    ),
                    max_pattern_length=long_config.get(
                        "max_pattern_length", MAX_LONG_PATTERN_LENGTH
                    ),
                    min_repetitions=long_config.get(
                        "min_repetitions", LONG_PATTERN_MIN_REPETITIONS
                    ),
                    max_history=long_config.get("max_history", MAX_ROLLING_HISTORY),
                )
        else:
            # Handle config object
            self.short_detector.update_config(new_config)

        # Reset state after configuration change
        self.reset()

    def _save_state(self) -> HybridDetectorInternalState:
        """Save current state for restoration."""
        # Note: short_detector._save_state() returns LoopDetectorInternalState,
        # but we store it as dict in HybridDetectorInternalState for simplicity/compatibility
        # or we should update HybridDetectorInternalState to use LoopDetectorInternalState
        return HybridDetectorInternalState(
            short_detector_state=self.short_detector._save_state().model_dump(),
            long_detector_content=self.long_detector.content,
            loop_events=self._loop_events.copy(),
            long_detector_last_check_length=getattr(
                self.long_detector, "_last_check_length", 0
            ),
        )

    def _restore_state(self, state: HybridDetectorInternalState) -> None:
        """Restore saved state."""
        # We need to convert the dict back to LoopDetectorInternalState if we used model_dump()
        from src.loop_detection.types import LoopDetectorInternalState

        short_state = LoopDetectorInternalState(**state.short_detector_state)
        self.short_detector._restore_state(short_state)
        self.long_detector.content = state.long_detector_content
        if hasattr(self.long_detector, "_last_check_length"):
            self.long_detector._last_check_length = max(
                0,
                min(
                    getattr(state, "long_detector_last_check_length", 0),
                    len(self.long_detector.content),
                ),
            )
        self._loop_events = state.loop_events
