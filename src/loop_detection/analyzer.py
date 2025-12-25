from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from .config import InternalLoopDetectionConfig
from .event import LoopDetectionEvent
from .hasher import ContentHasher

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PatternAnalyzerState:
    """Full snapshot of the PatternAnalyzer state for restoration."""

    stream_history: str
    content_stats: dict[str, list[int]]
    last_chunk_index: int
    in_code_block: bool
    history: list[LoopDetectionEvent]


@dataclass(frozen=True)
class PatternAnalyzerSummary:
    """Lightweight summary of the PatternAnalyzer state."""

    stream_history_len: int
    last_chunk_index: int
    in_code_block: bool
    content_stats_keys: list[str]
    history_len: int


class PatternAnalyzer:
    """Analyzes content streams for repetitive patterns using hash-based detection."""

    _stream_history: str
    _content_stats: dict[str, list[int]]
    _last_chunk_index: int
    _in_code_block: bool

    def __init__(self, config: InternalLoopDetectionConfig, hasher: ContentHasher):
        self.config = config
        self.hasher = hasher
        self.history: list[LoopDetectionEvent] = []  # To store detected events
        # Compiled regex for skipping chunks with markdown elements
        self._skip_pattern = re.compile(
            r"(^|\n)\s*((\|.*\|)|([|+-]{3,})|([*-+]|\d+\.)\s)|^[+-_=*\u2500-\u257F]+$",
            re.MULTILINE,
        )
        self.reset()

    def analyze_chunk(
        self, new_content: str, full_buffer_content: str
    ) -> LoopDetectionEvent | None:
        """Process new content using the fast hash-chunk algorithm."""
        if not self.ingest_chunk(new_content):
            return None

        return self.analyze_pending_stream(full_buffer_content)

    def ingest_chunk(self, new_content: str) -> bool:
        """Ingest new content while updating the analyzer state.

        Returns True when the chunk should be considered for loop analysis.
        Returns False when analysis should be skipped because the chunk either
        enters/exits a code block or triggers a full reset via markdown
        elements.
        """
        num_fences = new_content.count("```")
        if num_fences > 0 and num_fences % 2 != 0:
            self._in_code_block = not self._in_code_block

        # If we are entering or currently in a code block,
        # reset history and skip analysis for this chunk.
        if self._in_code_block:
            self._reset_history()
            return False

        # Check for other markdown elements that should reset the state.

        if self._skip_pattern.search(new_content):
            self.reset()  # Full reset for these elements
            return False

        self._stream_history += new_content
        self._truncate_and_update_indices()

        return True

    def analyze_pending_stream(
        self, full_buffer_content: str
    ) -> LoopDetectionEvent | None:
        """Run loop analysis on the ingested stream history."""
        while self._has_more_chunks_to_process():
            current_chunk = self._stream_history[
                self._last_chunk_index : self._last_chunk_index
                + self.config.content_chunk_size
            ]

            # Skip whitelisted patterns entirely to prevent them from polluting history
            if self._is_whitelisted_pattern(current_chunk):
                self._last_chunk_index += 1
                continue

            if len(current_chunk) < self.config.content_chunk_size:
                self._last_chunk_index += 1
                continue

            chunk_hash = self.hasher.hash(current_chunk)

            if self._is_loop_detected_for_chunk(current_chunk, chunk_hash):
                repetition_count = len(self._content_stats.get(chunk_hash, []))
                total_repeated_chars = len(current_chunk) * repetition_count
                event = self._create_detection_event_from_chunk(
                    pattern=current_chunk,
                    pattern_length=len(current_chunk),
                    repetition_count=repetition_count,
                    total_length=total_repeated_chars,
                    confidence=1.0,
                    buffer_content=full_buffer_content,
                )
                self.history.append(event)
                self._truncate_event_history_if_needed()
                return event

            self._last_chunk_index += 1

        return None

    def get_history(self) -> list[LoopDetectionEvent]:
        """Returns the history of detected loop events."""
        return self.history

    def get_state(self) -> PatternAnalyzerSummary:
        """Returns the current internal state summary of the analyzer."""
        return PatternAnalyzerSummary(
            stream_history_len=len(self._stream_history),
            last_chunk_index=self._last_chunk_index,
            in_code_block=self._in_code_block,
            content_stats_keys=list(self._content_stats.keys()),
            history_len=len(self.history),
        )

    def snapshot_state(self) -> PatternAnalyzerState:
        """Create a deep copy of the current internal state for later restoration."""
        return PatternAnalyzerState(
            stream_history=self._stream_history,
            content_stats={
                key: indices.copy() for key, indices in self._content_stats.items()
            },
            last_chunk_index=self._last_chunk_index,
            in_code_block=self._in_code_block,
            history=self.history.copy(),
        )

    def restore_state(self, state: PatternAnalyzerState) -> None:
        """Restore a previously captured state snapshot."""
        if not isinstance(state, PatternAnalyzerState) and isinstance(state, dict):
            # Backward compatibility for dict-based state if needed,
            # but here we strengthen it.
            # If we want to be safe, we could check if it's a dict and handle it.
            self._stream_history = state.get("stream_history", "")
            self._content_stats = {
                key: indices.copy()
                for key, indices in state.get("content_stats", {}).items()
            }
            self._last_chunk_index = state.get("last_chunk_index", 0)
            self._in_code_block = state.get("in_code_block", False)
            self.history = state.get("history", []).copy()
            return

        self._stream_history = state.stream_history
        self._content_stats = {
            key: indices.copy() for key, indices in state.content_stats.items()
        }
        self._last_chunk_index = state.last_chunk_index
        self._in_code_block = state.in_code_block
        self.history = state.history.copy()

    def _is_whitelisted_pattern(self, pattern: str) -> bool:
        """Check whether a detected pattern should be ignored based on the config whitelist."""
        whitelist = self.config.whitelist or []
        if not whitelist:
            return False

        cleaned_pattern = pattern.strip()
        if not cleaned_pattern:
            return True

        for entry in whitelist:
            token = entry.strip()
            if not token:
                continue

            if cleaned_pattern == token:
                return True

            if cleaned_pattern.replace(token, "") == "":
                return True

            token_chars = set(token)
            pattern_chars = set(cleaned_pattern)
            if len(token_chars) == 1 and pattern_chars == token_chars:
                return True

        return False

    def _truncate_event_history_if_needed(self) -> None:
        """Truncate event history if it exceeds maximum size to prevent memory leaks.

        Uses a reasonable default limit for event history (100 events) to prevent
        unbounded growth in long-running sessions. Each event can contain large
        buffer_content strings, so limiting the number of events is important.
        """
        # Use a reasonable default limit for event history
        # This is separate from max_history_length which is for stream characters
        max_event_history = 100

        if len(self.history) <= max_event_history:
            return

        # Remove oldest entries to keep only the most recent ones
        trunc_amount = len(self.history) - max_event_history
        self.history = self.history[trunc_amount:]

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Truncated pattern analyzer event history: removed %d oldest entries, keeping %d",
                trunc_amount,
                max_event_history,
            )

    def _truncate_and_update_indices(self) -> None:
        max_history = self.config.max_history_length
        if len(self._stream_history) <= max_history:
            # Even if stream_history is within limits, check if _content_stats needs cleanup
            # to prevent unbounded growth when many unique patterns are seen
            self._maybe_cleanup_content_stats()
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

    def _has_more_chunks_to_process(self) -> bool:
        return self._last_chunk_index + self.config.content_chunk_size <= len(
            self._stream_history
        )

    def _maybe_cleanup_content_stats(self) -> None:
        """Clean up _content_stats if it grows too large to prevent memory leaks.

        This prevents unbounded growth when many unique patterns are encountered
        even if stream_history stays within limits.

        Cleanup is called:
        - Periodically when adding new entries (every 1000 entries)
        - When stream history is truncated
        - When checking for loops (if dict exceeds threshold)
        """
        # Maximum number of unique hash entries to keep
        # This is separate from max_history_length and prevents dict growth
        max_content_stats_entries = 10000

        # Early return if within limits to avoid unnecessary work
        if len(self._content_stats) <= max_content_stats_entries:
            return

        # Remove entries with empty or invalid indices (they're no longer useful)
        # This happens when indices become negative after truncation
        cleaned_stats: dict[str, list[int]] = {}
        for h, indices in self._content_stats.items():
            valid_indices = [
                idx for idx in indices if idx >= 0 and idx < len(self._stream_history)
            ]
            if valid_indices:
                cleaned_stats[h] = valid_indices

        # If still too large, remove oldest entries (keep most recent)
        if len(cleaned_stats) > max_content_stats_entries:
            # Sort by highest index (most recent) and keep top N
            sorted_entries = sorted(
                cleaned_stats.items(),
                key=lambda x: max(x[1]) if x[1] else -1,
                reverse=True,
            )
            cleaned_stats = dict(sorted_entries[:max_content_stats_entries])
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Cleaned up _content_stats: removed %d oldest entries, keeping %d",
                    len(self._content_stats) - len(cleaned_stats),
                    len(cleaned_stats),
                )

        self._content_stats = cleaned_stats

    def _is_loop_detected_for_chunk(self, chunk: str, hash_hex: str) -> bool:
        existing_indices = self._content_stats.get(hash_hex)

        if not existing_indices:
            self._content_stats[hash_hex] = [self._last_chunk_index]
            # Clean up periodically when adding new entries to prevent unbounded growth
            # Check every 1000 new entries to balance performance and memory safety
            if len(self._content_stats) % 1000 == 0:
                self._maybe_cleanup_content_stats()
            return False

        first_index = existing_indices[0]
        original_chunk = self._stream_history[
            first_index : first_index + self.config.content_chunk_size
        ]
        if original_chunk != chunk:
            return False

        existing_indices.append(self._last_chunk_index)

        # Limit index list size to prevent memory leaks
        # We only need recent indices for loop detection, so keep at most
        # 2x the loop threshold to allow some history while preventing unbounded growth
        max_indices = self.config.content_loop_threshold * 2
        if len(existing_indices) > max_indices:
            # Keep only the most recent indices
            existing_indices[:] = existing_indices[-max_indices:]

        if len(existing_indices) < self.config.content_loop_threshold:
            return False

        recent_indices = existing_indices[-self.config.content_loop_threshold :]
        # Check if the indices are roughly periodic.
        distances = [
            recent_indices[i] - recent_indices[i - 1]
            for i in range(1, len(recent_indices))
        ]
        if not distances:
            return False

        # The distance should be at least the chunk size.
        # It can be larger due to noise. We allow some tolerance.
        average_distance = sum(distances) / len(distances)
        # Allow spacing up to 4x the chunk size so longer patterns (e.g. 250-300
        # chars) are still detected while keeping a guard against distant matches.
        max_allowed_distance = self.config.content_chunk_size * 4.0

        # All distances should be reasonably close to the chunk size or multiples.
        return (
            all(
                d >= self.config.content_chunk_size and d <= max_allowed_distance
                for d in distances
            )
            and average_distance <= max_allowed_distance
        )

    def _create_detection_event_from_chunk(
        self,
        *,
        pattern: str,
        pattern_length: int,
        repetition_count: int,
        total_length: int,
        confidence: float,
        buffer_content: str,
    ) -> LoopDetectionEvent:
        """Create a loop detection event for the current chunk pattern."""
        return LoopDetectionEvent(
            pattern=pattern,
            pattern_length=pattern_length,
            repetition_count=repetition_count,
            total_length=total_length,
            confidence=confidence,
            buffer_content=buffer_content,
            timestamp=time.time(),
        )

    def _reset_history(self) -> None:
        """Resets the stream history and content statistics, preserving code-block state."""
        self._stream_history = ""
        self._content_stats = {}
        self._last_chunk_index = 0
        self.history = []  # Clear history on full reset
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Pattern analyzer history reset")

    def reset(self) -> None:
        """Reset the entire analyzer state, including code-block tracking."""
        self._reset_history()
        self._in_code_block = False
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Pattern analyzer state reset")
