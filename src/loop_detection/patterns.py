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


class BlockAnalyzer:
    """
    Analyzes text for repeated blocks of 100+ characters.
    
    This class efficiently detects block repetitions that indicate LLM loops,
    focusing on substantial text blocks rather than character-level patterns.
    """
    
    def __init__(self, min_block_length: int = 100, max_block_length: int = 2000, whitelist: list[str] | None = None):
        """
        Initialize the block analyzer.
        
        Args:
            min_block_length: Minimum block length to consider (100+ chars)
            max_block_length: Maximum block length to analyze
            whitelist: List of patterns that should not trigger detection
        """
        self.min_block_length = max(min_block_length, 100)  # Enforce 100+ char minimum
        self.max_block_length = max_block_length
        self.whitelist = set(whitelist or [])
    
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
        for block_length in range(self.min_block_length, max_length + 1, 3):
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
        
        # Check each possible starting position
        for start_pos in range(len(text) - block_length + 1):
            if start_pos in processed_positions:
                continue
                
            block = text[start_pos:start_pos + block_length]
            
            # Skip if whitelisted
            if self.is_whitelisted(block):
                continue
            
            # Count consecutive repetitions starting from this position
            repetitions = 1
            current_pos = start_pos + block_length
            
            while current_pos + block_length <= len(text):
                next_block = text[current_pos:current_pos + block_length]
                if next_block == block:
                    repetitions += 1
                    current_pos += block_length
                else:
                    break
            
            # If we found enough repetitions, create a match
            if repetitions >= min_repetitions:
                confidence = self._calculate_block_confidence(block, repetitions)
                
                matches.append(BlockMatch(
                    block=block,
                    repetition_count=repetitions,
                    start_position=start_pos,
                    total_length=repetitions * block_length,
                    confidence=confidence
                ))
                
                # Mark all positions covered by this match as processed
                for pos in range(start_pos, current_pos):
                    processed_positions.add(pos)
        
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


# Backward compatibility alias
PatternAnalyzer = BlockAnalyzer
PatternMatch = BlockMatch

def find_patterns_in_text(text: str, min_repetitions: int = 2) -> list[BlockMatch]:
    """Backward compatibility function."""
    analyzer = BlockAnalyzer()
    return analyzer.find_blocks_in_text(text, min_repetitions)