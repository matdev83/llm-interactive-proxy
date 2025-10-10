"""
Loop detection implementation ported from Google's gemini-cli.

This is a direct port of the loop detection algorithm from:
https://github.com/google/generative-ai-docs/tree/main/gemini-cli

The algorithm is designed to work out-of-the-box without manual tuning and includes:
1. Smart context-aware tracking that resets when encountering markdown elements
2. Sliding window approach with fixed chunk size
3. Loop detection based on average distance between repeated chunks
4. Code block handling to avoid false positives in repetitive code structures
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from src.core.interfaces.loop_detector_interface import (
    ILoopDetector,
    LoopDetectionResult,
)
from src.loop_detection.event import LoopDetectionEvent

logger = logging.getLogger(__name__)

# Constants from gemini-cli
CONTENT_LOOP_THRESHOLD = 10  # Number of repetitions needed to trigger
CONTENT_CHUNK_SIZE = 50  # Size of chunks for hashing and comparison
MAX_HISTORY_LENGTH = 1000  # Maximum content to keep in memory


class GeminiCliLoopDetector(ILoopDetector):
    """
    Loop detector ported from Google's gemini-cli.

    This implementation uses a sliding window approach with intelligent context tracking
    to detect repetitive patterns in LLM responses without manual parameter tuning.
    """

    def __init__(
        self,
        content_loop_threshold: int = CONTENT_LOOP_THRESHOLD,
        content_chunk_size: int = CONTENT_CHUNK_SIZE,
        max_history_length: int = MAX_HISTORY_LENGTH,
    ):
        """
        Initialize the loop detector.

        Args:
            content_loop_threshold: Number of chunk repetitions to trigger detection (default: 10)
            content_chunk_size: Size of content chunks for comparison (default: 50 chars)
            max_history_length: Maximum content history to maintain (default: 1000 chars)
        """
        self.content_loop_threshold = content_loop_threshold
        self.content_chunk_size = content_chunk_size
        self.max_history_length = max_history_length

        # Content streaming tracking
        self.stream_content_history = ""
        self.content_stats: dict[str, list[int]] = {}
        self.last_content_index = 0
        self.loop_detected = False
        self.in_code_block = False

        # State tracking
        self._is_enabled = True
        self._loop_events: list[LoopDetectionEvent] = []

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "GeminiCliLoopDetector initialized: chunk_size=%d, threshold=%d, max_history=%d",
                self.content_chunk_size,
                self.content_loop_threshold,
                self.max_history_length,
            )

    def process_chunk(self, chunk: str) -> LoopDetectionEvent | None:
        """
        Process a chunk of content and check for loops.

        Args:
            chunk: Content chunk to process

        Returns:
            LoopDetectionEvent if a loop is detected, None otherwise
        """
        if self.loop_detected or not self._is_enabled or not chunk:
            return None

        self.loop_detected = self._check_content_loop(chunk)
        if self.loop_detected:
            import time

            event = LoopDetectionEvent(
                pattern="Repetitive content pattern detected",
                repetition_count=self.content_loop_threshold,
                total_length=self.content_chunk_size * self.content_loop_threshold,
                confidence=1.0,
                buffer_content=self.stream_content_history[-200:],  # Last 200 chars
                timestamp=time.time(),
            )
            self._loop_events.append(event)
            return event

        return None

    def _check_content_loop(self, content: str) -> bool:
        """
        Detects content loops by analyzing streaming text for repetitive patterns.

        The algorithm works by:
        1. Appending new content to the streaming history
        2. Truncating history if it exceeds the maximum length
        3. Analyzing content chunks for repetitive patterns using hashing
        4. Detecting loops when identical chunks appear frequently within a short distance
        5. Disabling loop detection within code blocks to prevent false positives

        Enhanced from gemini-cli: Only resets on code fences and dividers (clear boundaries),
        not on lists/headings/tables which might be part of the looping content itself.

        Args:
            content: New content chunk to analyze

        Returns:
            True if a loop is detected, False otherwise
        """
        # Track code fences and dividers (clear content boundaries)
        num_fences = content.count("```")
        is_divider = bool(re.match(r"^[+\-_=*\u2500-\u257F]+$", content.strip()))

        # Only reset on code fences or dividers, NOT on markdown elements like
        # lists/headings/tables/blockquotes, as these might be part of the repeating pattern itself!
        # This is a key difference from the original gemini-cli implementation which was too
        # aggressive with resets and missed loops containing structured markdown.
        if num_fences or is_divider:
            # Reset tracking when code boundaries or dividers are detected
            self._reset_content_tracking()
            self.loop_detected = False

        # Track code block state
        was_in_code_block = self.in_code_block
        if num_fences:
            self.in_code_block = (
                not self.in_code_block if num_fences % 2 == 1 else self.in_code_block
            )

        # Skip loop detection inside code blocks or for dividers
        if was_in_code_block or self.in_code_block or is_divider:
            return False

        # Reset on markdown structures that typically indicate new sections
        if self._should_reset_for_markdown_structure(content):
            self._reset_content_tracking()
            self.loop_detected = False
            return False

        self.stream_content_history += content

        self._truncate_and_update()
        return self._analyze_content_chunks_for_loop()

    def _should_reset_for_markdown_structure(self, content: str) -> bool:
        """Detect markdown structures that should reset tracking."""
        stripped = content.lstrip()
        if not stripped:
            return False

        # Headings (e.g. # Title)
        if re.match(r"^#{1,6}\s+", stripped):
            return True

        # Blockquotes (e.g. > Quote)
        if re.match(r"^>\s+", stripped):
            return True

        # Lists (unordered *, -, + or ordered 1.)
        if re.match(r"^(?:[*+\-]|\d+\.)\s+", stripped):
            return True

        # Markdown tables (header or separator rows)
        if stripped.startswith("|") and stripped.count("|") >= 2:
            return True
        return bool(re.match(r"^\+[-+]+\+", stripped))

    def _truncate_and_update(self) -> None:
        """
        Truncates the content history to prevent unbounded memory growth.
        When truncating, adjusts all stored indices to maintain their relative positions.
        """
        if len(self.stream_content_history) <= self.max_history_length:
            return

        # Calculate how much content to remove from the beginning
        truncation_amount = len(self.stream_content_history) - self.max_history_length
        self.stream_content_history = self.stream_content_history[truncation_amount:]
        self.last_content_index = max(0, self.last_content_index - truncation_amount)

        # Update all stored chunk indices to account for the truncation
        for hash_val, old_indices in list(self.content_stats.items()):
            adjusted_indices = [
                idx - truncation_amount
                for idx in old_indices
                if idx >= truncation_amount
            ]

            if adjusted_indices:
                self.content_stats[hash_val] = adjusted_indices
            else:
                del self.content_stats[hash_val]

    def _analyze_content_chunks_for_loop(self) -> bool:
        """
        Analyzes content in fixed-size chunks to detect repetitive patterns.

        Uses a sliding window approach:
        1. Extract chunks of fixed size (content_chunk_size)
        2. Hash each chunk for efficient comparison
        3. Track positions where identical chunks appear
        4. Detect loops when chunks repeat frequently within a short distance

        Returns:
            True if a loop is detected, False otherwise
        """
        while self._has_more_chunks_to_process():
            # Extract current chunk of text
            current_chunk = self.stream_content_history[
                self.last_content_index : self.last_content_index
                + self.content_chunk_size
            ]
            chunk_hash = hashlib.sha256(current_chunk.encode("utf-8")).hexdigest()

            if self._is_loop_detected_for_chunk(current_chunk, chunk_hash):
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Loop detected: chunk repeated %d times within short distance",
                        self.content_loop_threshold,
                    )
                return True

            # Move to next position in the sliding window
            self.last_content_index += 1

        return False

    def _has_more_chunks_to_process(self) -> bool:
        """Check if there are more chunks to process in the sliding window."""
        return self.last_content_index + self.content_chunk_size <= len(
            self.stream_content_history
        )

    def _is_loop_detected_for_chunk(self, chunk: str, hash_val: str) -> bool:
        """
        Determines if a content chunk indicates a loop pattern.

        Loop detection logic:
        1. Check if we've seen this hash before (new chunks are stored for future comparison)
        2. Verify actual content matches to prevent hash collisions
        3. Track all positions where this chunk appears
        4. A loop is detected when the same chunk appears content_loop_threshold times
           within a small average distance (<=1.5 * chunk size)

        Args:
            chunk: Current content chunk
            hash_val: SHA256 hash of the chunk

        Returns:
            True if a loop is detected for this chunk, False otherwise
        """
        existing_indices = self.content_stats.get(hash_val)

        if existing_indices is None:
            self.content_stats[hash_val] = [self.last_content_index]
            return False

        # Verify actual content match to prevent hash collisions
        if not self._is_actual_content_match(chunk, existing_indices[0]):
            return False

        existing_indices.append(self.last_content_index)

        if len(existing_indices) < self.content_loop_threshold:
            return False

        # Analyze the most recent occurrences to see if they're clustered closely together
        recent_indices = existing_indices[-self.content_loop_threshold :]
        total_distance = recent_indices[-1] - recent_indices[0]
        average_distance = total_distance / (self.content_loop_threshold - 1)
        max_allowed_distance = self.content_chunk_size * 1.5

        return average_distance <= max_allowed_distance

    def _is_actual_content_match(self, current_chunk: str, original_index: int) -> bool:
        """
        Verifies that two chunks with the same hash actually contain identical content.
        This prevents false positives from hash collisions.

        Args:
            current_chunk: Current content chunk
            original_index: Index of the original chunk with the same hash

        Returns:
            True if chunks match exactly, False otherwise
        """
        original_chunk = self.stream_content_history[
            original_index : original_index + self.content_chunk_size
        ]
        return original_chunk == current_chunk

    def _reset_content_tracking(self, reset_history: bool = True) -> None:
        """
        Resets content tracking state.

        Args:
            reset_history: If True, also clears the content history
        """
        if reset_history:
            self.stream_content_history = ""
        self.content_stats.clear()
        self.last_content_index = 0

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

        # Temporarily reset state
        original_state = self._save_state()
        self.reset()

        # Process the entire content
        event = self.process_chunk(content)

        # Restore state
        self._restore_state(original_state)

        if event is None:
            return LoopDetectionResult(has_loop=False)

        return LoopDetectionResult(
            has_loop=True,
            pattern=event.pattern,
            repetitions=event.repetition_count,
            details={
                "pattern_length": self.content_chunk_size,
                "total_repeated_chars": event.total_length,
            },
        )

    def enable(self) -> None:
        """Enable loop detection."""
        self._is_enabled = True
        if logger.isEnabledFor(logging.INFO):
            logger.info("Loop detection enabled")

    def disable(self) -> None:
        """Disable loop detection."""
        self._is_enabled = False
        if logger.isEnabledFor(logging.INFO):
            logger.info("Loop detection disabled")

    def is_enabled(self) -> bool:
        """Check if loop detection is enabled."""
        return self._is_enabled

    def reset(self) -> None:
        """Reset all loop detection state."""
        self._reset_content_tracking(reset_history=True)
        self.loop_detected = False
        self.in_code_block = False
        self._loop_events.clear()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Loop detector state reset")

    def get_stats(self) -> dict[str, Any]:
        """Get detector statistics."""
        return {
            "is_enabled": self._is_enabled,
            "loop_detected": self.loop_detected,
            "history_length": len(self.stream_content_history),
            "in_code_block": self.in_code_block,
            "tracked_chunks": len(self.content_stats),
            "config": {
                "content_chunk_size": self.content_chunk_size,
                "content_loop_threshold": self.content_loop_threshold,
                "max_history_length": self.max_history_length,
            },
        }

    def get_loop_history(self) -> list[LoopDetectionEvent]:
        """Get history of detected loops."""
        return self._loop_events.copy()

    def get_current_state(self) -> dict[str, Any]:
        """Get current internal state."""
        return {
            "stream_content_history_length": len(self.stream_content_history),
            "last_content_index": self.last_content_index,
            "loop_detected": self.loop_detected,
            "in_code_block": self.in_code_block,
            "content_stats_size": len(self.content_stats),
        }

    def update_config(self, new_config: Any) -> None:
        """
        Update detector configuration.

        Args:
            new_config: New configuration (can be dict or config object)
        """
        if hasattr(new_config, "content_chunk_size"):
            self.content_chunk_size = new_config.content_chunk_size
        elif isinstance(new_config, dict) and "content_chunk_size" in new_config:
            self.content_chunk_size = new_config["content_chunk_size"]

        if hasattr(new_config, "content_loop_threshold"):
            self.content_loop_threshold = new_config.content_loop_threshold
        elif isinstance(new_config, dict) and "content_loop_threshold" in new_config:
            self.content_loop_threshold = new_config["content_loop_threshold"]

        if hasattr(new_config, "max_history_length"):
            self.max_history_length = new_config.max_history_length
        elif isinstance(new_config, dict) and "max_history_length" in new_config:
            self.max_history_length = new_config["max_history_length"]

        # Reset state after configuration change
        self.reset()

    def _save_state(self) -> dict[str, Any]:
        """Save current state for restoration."""
        return {
            "stream_content_history": self.stream_content_history,
            "content_stats": {
                hash_hex: indices.copy()
                for hash_hex, indices in self.content_stats.items()
            },
            "last_content_index": self.last_content_index,
            "loop_detected": self.loop_detected,
            "in_code_block": self.in_code_block,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        """Restore saved state."""
        self.stream_content_history = state["stream_content_history"]
        self.content_stats = state["content_stats"]
        self.last_content_index = state["last_content_index"]
        self.loop_detected = state["loop_detected"]
        self.in_code_block = state["in_code_block"]
