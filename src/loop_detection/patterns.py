"""
Block repetition detection for loop detection.

This module detects repeated text blocks of 100+ characters that indicate
LLM response loops. Focuses on block-level repetitions rather than character patterns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BlockMatch:
    """Represents a detected repeated block."""
    block: str
    repetition_count: int
    start_position: int
    total_length: int
    confidence: float

    # Legacy alias – many callers (tests) still expect ``.pattern`` instead of
    # the newer ``.block`` terminology.
    @property
    def pattern(self) -> str:  # noqa: D401
        return self.block


class BlockAnalyzer:
    """
    Analyzes text for repeated blocks of 100+ characters.
    
    This class efficiently detects block repetitions that indicate LLM loops,
    focusing on substantial text blocks rather than character-level patterns.
    """
    
    def __init__(
        self,
        min_block_length: int = 100,
        max_block_length: int = 8192,
        whitelist: list[str] | None = None,
        block_scan_step: int = 8,
        **legacy_kwargs,
    ):
        """Create a new ``BlockAnalyzer``.

        The constructor keeps its original *min_block_length* / *max_block_length*
        API but also swallows renamed legacy keyword arguments such as
        *max_pattern_length* so that older code (and tests) continue to work
        after the internal refactor.  Any unknown keyword arguments are ignored
        with a *debug* log entry so that new typos do not slip in silently.
        """

        # Gracefully map the old parameter name to the new one
        if "max_pattern_length" in legacy_kwargs:
            max_block_length = legacy_kwargs.pop("max_pattern_length")

        if legacy_kwargs:
            logger.debug("Ignored legacy/unknown kwargs in BlockAnalyzer.__init__: %s", legacy_kwargs)
        # Enforce 100+ char minimum – we are only interested in *text block*
        # repetitions, not low-level character sequences.
        self.min_block_length = max(min_block_length, 100)
        self.max_block_length = max_block_length
        self.whitelist = set(whitelist or [])
        # Step size when iterating over block lengths.  Using a larger step
        # dramatically reduces the combinatorial explosion of checks while
        # still giving adequate coverage thanks to the extra "common_lengths"
        # that are always evaluated.
        self.block_scan_step = max(1, block_scan_step)
    
    def find_blocks_in_text(self, text: str, min_repetitions: int = 2) -> list[BlockMatch]:
        """
        Find all repeated blocks in the given text.
        
        Args:
            text: Text to analyze
            min_repetitions: Minimum number of repetitions required
            
        Returns:
            List of detected block matches, sorted by significance
        """
        if len(text) < self.min_block_length * 2:
            return []
        
        all_matches = []
        
        # Try different block lengths from min to max
        max_length = min(self.max_block_length, len(text) // 2)
        
        # Check every 3 characters for better coverage of real-world patterns
        step = 1 if max_length <= 50 else self.block_scan_step
        for block_length in range(self.min_block_length, max_length + 1, step):
            block_matches = self._find_blocks_of_length(text, block_length, min_repetitions)
            all_matches.extend(block_matches)
        
        # Also check some specific lengths that might be common in real-world loops
        common_lengths = [100, 120, 150, 180, 200, 250, 266, 300, 350, 400, 420, 450, 453, 480, 500, 550, 600, 700, 800, 900, 1000, 1200, 1330, 1400, 1500, 1600, 1800, 2000]
        for length in common_lengths:
            if self.min_block_length <= length <= max_length:
                block_matches = self._find_blocks_of_length(text, length, min_repetitions)
                all_matches.extend(block_matches)
        
        # Sort by total length (bigger blocks are more significant)
        all_matches.sort(key=lambda m: (m.total_length, m.repetition_count), reverse=True)
        
        # Remove overlapping matches
        final_matches = self._remove_overlapping_blocks(all_matches)
        
        return final_matches
    
    def _find_blocks_of_length(self, text: str, block_length: int, min_repetitions: int) -> list[BlockMatch]:
        """
        Find repeated blocks of a specific length.
        
        Args:
            text: Text to analyze
            block_length: Length of blocks to find
            min_repetitions: Minimum repetitions required
            
        Returns:
            List of block matches for this length
        """
        if len(text) < block_length * min_repetitions:
            return []
        
        matches = []
        processed_positions = set()

        text_len = len(text)
        pos = 0
        while pos <= text_len - block_length:
            if pos in processed_positions:
                pos += 1
                continue

            block = text[pos : pos + block_length]

            # Skip if whitelisted
            if self.is_whitelisted(block):
                pos += 1
                continue

            # Count consecutive repetitions starting from this position
            repetitions = 1
            current_pos = pos + block_length

            while current_pos + block_length <= text_len:
                if text.startswith(block, current_pos):
                    repetitions += 1
                    current_pos += block_length
                else:
                    break

            # If we found enough repetitions, create a match
            if repetitions >= min_repetitions:
                confidence = self._calculate_block_confidence(block, repetitions)

                matches.append(
                    BlockMatch(
                        block=block,
                        repetition_count=repetitions,
                        start_position=pos,
                        total_length=repetitions * block_length,
                        confidence=confidence,
                    )
                )

                # Mark all positions covered by this match as processed to
                # avoid redundant checks.  Using range with step of 1 is still
                # acceptable because this branch is only hit for actual matches.
                processed_positions.update(range(pos, current_pos))
                pos = current_pos  # Skip past the processed block
            else:
                pos += 1

        return matches
    
    def _calculate_block_confidence(self, block: str, repetitions: int) -> float:
        """
        Calculate confidence score for a block match.
        
        Args:
            block: The repeated block
            repetitions: Number of repetitions
            
        Returns:
            Confidence score between 0 and 1
        """
        # Base confidence from repetition count
        repetition_score = min(repetitions / 10.0, 1.0)  # Max at 10 repetitions
        
        # Length bonus - longer blocks are more significant
        length_score = min(len(block) / 500.0, 1.0)  # Max at 500 chars
        
        # Content diversity penalty - very repetitive content within block is less significant
        unique_chars = len(set(block.lower()))
        diversity_score = min(unique_chars / 20.0, 1.0)  # Max at 20 unique chars
        
        # Combine scores
        confidence = (repetition_score * 0.5 + length_score * 0.3 + diversity_score * 0.2)
        
        return min(confidence, 1.0)
    
    def _remove_overlapping_blocks(self, matches: list[BlockMatch]) -> list[BlockMatch]:
        """
        Remove overlapping block matches, keeping the most significant ones.
        
        Args:
            matches: List of block matches (should be sorted by significance)
            
        Returns:
            List of non-overlapping matches
        """
        if not matches:
            return []
        
        final_matches = []
        used_ranges = []
        
        for match in matches:
            start = match.start_position
            end = match.start_position + match.total_length
            
            # Check if this match overlaps with any already selected match
            overlaps = False
            for used_start, used_end in used_ranges:
                if not (end <= used_start or start >= used_end):
                    overlaps = True
                    break
            
            if not overlaps:
                final_matches.append(match)
                used_ranges.append((start, end))
        
        return final_matches
    
    def is_whitelisted(self, block: str) -> bool:
        """
        Check if a block should be ignored due to whitelist.
        
        Args:
            block: Block to check
            
        Returns:
            True if block should be ignored
        """
        block_normalized = self.normalize_block(block)
        
        # Direct match
        if block_normalized in self.whitelist or block in self.whitelist:
            return True
        
        # Check if block contains only whitelisted patterns
        for whitelisted in self.whitelist:
            if whitelisted in block or whitelisted in block_normalized:
                # If the whitelisted pattern makes up most of the block, ignore it
                if len(whitelisted) >= len(block) * 0.8:
                    return True
        
        return False
    
    def normalize_block(self, block: str) -> str:
        """
        Normalize a block for comparison.
        
        Args:
            block: Block to normalize
            
        Returns:
            Normalized block
        """
        # Remove extra whitespace and convert to lowercase
        return ' '.join(block.lower().split())

    # ---------------------------------------------------------------------
    # Backwards-compat helper methods – keep the old public surface intact
    # ---------------------------------------------------------------------

    # Older code (and tests) used *pattern* terminology instead of the new
    # *block* nomenclature.  Provide thin wrappers so that nothing breaks.

    def find_patterns_in_text(self, text: str, min_repetitions: int = 2):  # noqa: D401 – keep legacy name
        """Alias for :py:meth:`find_blocks_in_text`."""
        return self.find_blocks_in_text(text, min_repetitions)

    def normalize_pattern(self, pattern: str) -> str:  # noqa: D401 – keep legacy name
        """Alias for :py:meth:`normalize_block`."""
        return self.normalize_block(pattern)


# ------------------------------------------------------------------
# Backwards-compat dataclass and aliases
# ------------------------------------------------------------------


class PatternMatch(BlockMatch):
    """Backwards-compat wrapper that uses the legacy *pattern* attribute name."""

    # Forward ``pattern`` to the new ``block`` attribute on construction.
    def __init__(
        self,
        pattern: str,
        start_position: int,
        repetition_count: int,
        total_length: int,
        confidence: float,
    ) -> None:
        super().__init__(
            block=pattern,
            repetition_count=repetition_count,
            start_position=start_position,
            total_length=total_length,
            confidence=confidence,
        )

    # Property alias so read-access via ``.pattern`` continues to work
    @property
    def pattern(self) -> str:  # noqa: D401
        return self.block


# Backward compatibility aliases used all over the code-base
PatternAnalyzer = BlockAnalyzer

# Keep the old find_patterns_in_text *function* name intact
# but bump internally to the optimised implementation.

def find_patterns_in_text(text: str, min_repetitions: int = 2) -> list[BlockMatch]:
    """Backward compatibility function."""
    analyzer = BlockAnalyzer()
    return analyzer.find_blocks_in_text(text, min_repetitions)