"""
Pattern analysis utilities for loop detection.

This module provides efficient algorithms for detecting repetitive patterns
in text streams, including sliding window detection and rolling hash
implementations for optimal performance.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class PatternMatch:
    """Represents a detected pattern match."""
    pattern: str
    start_position: int
    repetition_count: int
    total_length: int
    confidence: float = 1.0


class RollingHash:
    """Efficient rolling hash implementation for pattern matching."""
    
    def __init__(self, base: int = 256, modulus: int = 10**9 + 7):
        self.base = base
        self.modulus = modulus
        self.hash_value = 0
        self.length = 0
        self.base_power = 1
        # Pre-compute multiplicative inverse of ``base`` modulo ``modulus``
        # so that we can update ``base_power`` in O(1) during character
        # removal without an expensive ``pow`` call on every step.
        # The modulus is prime (1e9+7) so ``base^(mod-2)`` is the inverse.
        self._base_inv = pow(self.base, self.modulus - 2, self.modulus)
    
    def add_char(self, char: str) -> int:
        """Add a character to the rolling hash."""
        self.hash_value = (self.hash_value * self.base + ord(char)) % self.modulus
        self.length += 1
        if self.length > 1:
            self.base_power = (self.base_power * self.base) % self.modulus
        return self.hash_value
    
    def remove_char(self, char: str) -> int:
        """Remove the oldest character from the rolling hash."""
        if self.length == 0:
            return self.hash_value
        
        self.hash_value = (self.hash_value - ord(char) * self.base_power) % self.modulus
        if self.hash_value < 0:
            self.hash_value += self.modulus
        
        self.length -= 1
        if self.length > 0:
            # Multiply by the cached modular inverse instead of recomputing
            self.base_power = (self.base_power * self._base_inv) % self.modulus
        else:
            self.base_power = 1
        
        return self.hash_value
    
    def get_hash(self) -> int:
        """Get current hash value."""
        return self.hash_value
    
    def reset(self):
        """Reset the rolling hash."""
        self.hash_value = 0
        self.length = 0
        self.base_power = 1


class PatternAnalyzer:
    """Analyzes text for repetitive patterns using efficient algorithms."""
    
    def __init__(self, max_pattern_length: int = 500, whitelist: Optional[List[str]] = None):
        self.max_pattern_length = max_pattern_length
        self.whitelist = set(whitelist or [])
        
        # Pattern lengths to check (powers of 2 + some common sizes)
        self.pattern_lengths = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16, 20, 24, 32, 40, 50, 64, 100, 128, 256]
        self.pattern_lengths = [l for l in self.pattern_lengths if l <= max_pattern_length]
        

    def normalize_pattern(self, pattern: str) -> str:
        """Normalize a pattern for consistent comparison."""
        # Strip leading/trailing whitespace
        normalized = pattern.strip()
        
        # Replace multiple consecutive whitespace with single space
        import re
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized
    
    def is_whitelisted(self, pattern: str) -> bool:
        """Check if pattern is in the whitelist."""
        normalized = self.normalize_pattern(pattern)
        
        # Direct match
        if normalized in self.whitelist or pattern in self.whitelist:
            return True
        
        # Check if pattern is part of any whitelisted pattern
        for whitelisted in self.whitelist:
            if pattern in whitelisted or normalized in whitelisted:
                return True
            # Also check if whitelisted pattern is part of the detected pattern
            if whitelisted in pattern or whitelisted in normalized:
                return True
        
        return False
    
    def find_patterns_in_text(self, text: str, min_repetitions: int = 2) -> List[PatternMatch]:
        """Find all repetitive patterns in the given text."""
        if not text or len(text) < 2:
            return []
        
        matches = []
        text_length = len(text)
        
        # Check each pattern length
        for pattern_length in self.pattern_lengths:
            if pattern_length > text_length // 2:
                continue
            
            pattern_matches = self._find_patterns_of_length(
                text, pattern_length, min_repetitions
            )
            matches.extend(pattern_matches)
        
        # Sort by confidence and repetition count
        matches.sort(key=lambda m: (m.confidence, m.repetition_count), reverse=True)
        
        # Remove overlapping matches (keep the best ones)
        return self._remove_overlapping_matches(matches)
    
    def _find_patterns_of_length(self, text: str, pattern_length: int, min_repetitions: int) -> List[PatternMatch]:
        """Find repetitive patterns of a specific length."""
        if len(text) < pattern_length * min_repetitions:
            return []
        
        matches = []
        hash_to_positions: Dict[int, List[int]] = defaultdict(list)
        rolling_hash = RollingHash()
        
        # Build initial hash for first pattern
        for i in range(pattern_length):
            rolling_hash.add_char(text[i])
        
        initial_hash = rolling_hash.get_hash()
        hash_to_positions[initial_hash].append(0)
        
        # Roll through the text
        for i in range(pattern_length, len(text)):
            # Remove old character and add new one
            rolling_hash.remove_char(text[i - pattern_length])
            rolling_hash.add_char(text[i])
            
            current_hash = rolling_hash.get_hash()
            current_pos = i - pattern_length + 1
            
            hash_to_positions[current_hash].append(current_pos)
        
        # Analyze hash collisions for repetitions
        for hash_value, positions in hash_to_positions.items():
            if len(positions) < min_repetitions:
                continue
            
            # Verify actual string matches (hash collisions are possible)
            pattern_groups = self._group_consecutive_patterns(text, positions, pattern_length)
            
            for group in pattern_groups:
                if len(group) >= min_repetitions:
                    pattern = text[group[0]:group[0] + pattern_length]
                    
                    # Skip if whitelisted - check both the pattern and if any whitelist item appears in the source text
                    if self.is_whitelisted(pattern):
                        continue
                    
                    # Also check if any whitelisted pattern appears in the source text around this location
                    start_pos = max(0, group[0] - pattern_length)
                    end_pos = min(len(text), group[0] + len(group) * pattern_length + pattern_length)
                    context = text[start_pos:end_pos]
                    
                    should_skip = False
                    for whitelisted in self.whitelist:
                        if whitelisted in context:
                            should_skip = True
                            break
                    
                    if should_skip:
                        continue
                    
                    # Calculate confidence based on pattern characteristics
                    confidence = self._calculate_pattern_confidence(pattern, len(group))
                    
                    match = PatternMatch(
                        pattern=pattern,
                        start_position=group[0],
                        repetition_count=len(group),
                        total_length=len(group) * pattern_length,
                        confidence=confidence
                    )
                    matches.append(match)
        
        return matches
    
    def _group_consecutive_patterns(self, text: str, positions: List[int], pattern_length: int) -> List[List[int]]:
        """Group positions that represent consecutive repetitions of the same pattern."""
        if not positions:
            return []
        
        # Sort positions
        positions.sort()
        
        groups = []
        current_group = [positions[0]]
        expected_next = positions[0] + pattern_length
        
        for pos in positions[1:]:
            # Verify the pattern actually matches
            pattern1 = text[current_group[0]:current_group[0] + pattern_length]
            pattern2 = text[pos:pos + pattern_length]
            
            if pos == expected_next and pattern1 == pattern2:
                # Consecutive repetition
                current_group.append(pos)
                expected_next = pos + pattern_length
            else:
                # Start new group
                if len(current_group) > 1:
                    groups.append(current_group)
                current_group = [pos]
                expected_next = pos + pattern_length
        
        # Add the last group
        if len(current_group) > 1:
            groups.append(current_group)
        
        return groups
    
    def _calculate_pattern_confidence(self, pattern: str, repetition_count: int) -> float:
        """Calculate confidence score for a pattern match."""
        confidence = 1.0
        
        # Lower confidence for very short patterns
        if len(pattern) == 1:
            confidence *= 0.7
        elif len(pattern) == 2:
            confidence *= 0.8
        elif len(pattern) <= 5:
            confidence *= 0.9
        
        # Higher confidence for more repetitions
        if repetition_count >= 10:
            confidence *= 1.2
        elif repetition_count >= 5:
            confidence *= 1.1
        
        # Lower confidence for patterns that are mostly whitespace
        non_whitespace_ratio = len(pattern.strip()) / len(pattern) if pattern else 0
        confidence *= (0.5 + 0.5 * non_whitespace_ratio)
        
        # Lower confidence for patterns with very few unique characters
        unique_chars = len(set(pattern))
        if unique_chars == 1:
            confidence *= 0.6
        elif unique_chars == 2:
            confidence *= 0.8
        
        return min(confidence, 1.0)
    
    def _remove_overlapping_matches(self, matches: List[PatternMatch]) -> List[PatternMatch]:
        """Remove overlapping matches, keeping the best ones."""
        if not matches:
            return []
        
        # Sort by start position
        sorted_matches = sorted(matches, key=lambda m: m.start_position)
        
        result = []
        last_end = -1
        
        for match in sorted_matches:
            match_start = match.start_position
            match_end = match.start_position + match.total_length
            
            if match_start >= last_end:
                # No overlap
                result.append(match)
                last_end = match_end
            else:
                # Overlap - keep the better match
                if result and match.confidence > result[-1].confidence:
                    result[-1] = match
                    last_end = match_end
        
        return result
    
    def analyze_streaming_chunk(self, chunk: str, context: str = "") -> List[PatternMatch]:
        """Analyze a chunk of streaming text with optional context."""
        # Combine context with new chunk for analysis
        full_text = context + chunk
        
        # Find patterns in the combined text
        matches = self.find_patterns_in_text(full_text)
        
        # Filter matches that involve the new chunk
        chunk_start = len(context)
        relevant_matches = []
        
        for match in matches:
            match_end = match.start_position + match.total_length
            
            # Keep matches that overlap with the new chunk
            if match_end > chunk_start:
                relevant_matches.append(match)
        
        return relevant_matches