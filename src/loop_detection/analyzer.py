from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from src.core.interfaces.model_bases import InternalDTO

from .config import LoopDetectionConfig
from .hasher import ContentHasher

logger = logging.getLogger(__name__)


@dataclass
class LoopDetectionEvent(InternalDTO):
    """Event triggered when a loop is detected."""

    pattern: str
    repetition_count: int
    total_length: int
    confidence: float
    buffer_content: str
    timestamp: float


class PatternAnalyzer:
    """Analyzes content streams for repetitive patterns using hash-based detection."""

    _stream_history: str
    _content_stats: dict[str, list[int]]
    _last_chunk_index: int
    _in_code_block: bool

    def __init__(self, config: LoopDetectionConfig, hasher: ContentHasher):
        self.config = config
        self.hasher = hasher
        self.reset()

    def analyze_chunk(
        self, new_content: str, full_buffer_content: str
    ) -> LoopDetectionEvent | None:
        """Process new content using the fast hash-chunk algorithm."""
        num_fences = new_content.count("```")
        if num_fences > 0 and num_fences % 2 != 0:
            self._in_code_block = not self._in_code_block

        # If we are entering or currently in a code block,
        # reset history and skip analysis for this chunk.
        if self._in_code_block:
            self._reset_history()
            return None

        # Check for other markdown elements that should reset the state.
        has_table = bool(re.search(r"(^|\n)\s*(\|.*\||[|+-]{3,})", new_content))
        has_list_item = bool(re.search(r"(^|\n)\s*[*-+]\s", new_content)) or bool(
            re.search(r"(^|\n)\s*\d+\.\s", new_content)
        )
        has_heading = bool(re.search(r"(^|\n)#+\s", new_content))
        has_blockquote = bool(re.search(r"(^|\n)>\s", new_content))
        is_divider = bool(re.match(r"^[+-_=*\u2500-\u257F]+$", new_content))

        if has_table or has_list_item or has_heading or has_blockquote or is_divider:
            self.reset()  # Full reset for these elements
            return None

        self._stream_history += new_content
        self._truncate_and_update_indices()

        while self._has_more_chunks_to_process():
            current_chunk = self._stream_history[
                self._last_chunk_index : self._last_chunk_index
                + self.config.content_chunk_size
            ]
            chunk_hash = self.hasher.hash(current_chunk)

            if self._is_loop_detected_for_chunk(current_chunk, chunk_hash):
                return self._create_detection_event_from_chunk(
                    pattern=current_chunk,
                    repetition_count=len(self._content_stats[chunk_hash]),
                    total_length=len(self._stream_history),
                    confidence=1.0,
                    buffer_content=full_buffer_content,
                )

            self._last_chunk_index += 1

        return None

    def _truncate_and_update_indices(self) -> None:
        max_history = self.config.max_history_length
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

    def _has_more_chunks_to_process(self) -> bool:
        return self._last_chunk_index + self.config.content_chunk_size <= len(
            self._stream_history
        )

    def _is_loop_detected_for_chunk(self, chunk: str, hash_hex: str) -> bool:
        existing_indices = self._content_stats.get(hash_hex)

        if not existing_indices:
            self._content_stats[hash_hex] = [self._last_chunk_index]
            return False

        first_index = existing_indices[0]
        original_chunk = self._stream_history[
            first_index : first_index + self.config.content_chunk_size
        ]
        if original_chunk != chunk:
            return False

        existing_indices.append(self._last_chunk_index)

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
        max_allowed_distance = self.config.content_chunk_size * 2.0

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
        repetition_count: int,
        total_length: int,
        confidence: float,
        buffer_content: str,
    ) -> LoopDetectionEvent:
        """Create a loop detection event for the current chunk pattern."""
        return LoopDetectionEvent(
            pattern=pattern,
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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Pattern analyzer history reset")

    def reset(self) -> None:
        """Reset the entire analyzer state, including code-block tracking."""
        self._reset_history()
        self._in_code_block = False
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Pattern analyzer state reset")
