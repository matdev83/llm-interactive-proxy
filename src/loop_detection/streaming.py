"""
Streaming response utilities for loop detection integration.

This module provides wrappers and utilities for integrating loop detection
with streaming responses from LLM backends.
"""

from __future__ import annotations

import logging

from .detector import LoopDetectionEvent, LoopDetector

logger = logging.getLogger(__name__)


def _detect_simple_repetition(text: str) -> tuple[str | None, int]:
    """Naive fallback: detect short substring repeated consecutively at least 3 times.

    Looks for 1-6 char token repeated; returns (pattern, count) or (None, 0).

    PERFORMANCE: Optimized to skip redundant positions after finding repeats.
    """
    try:
        # Fast path: common noisy token
        token = "ERROR "
        if token in text:
            count = text.count(token)
            return (token.strip(), count)

        # PERFORMANCE: Limit text length early to avoid slicing costs in loop
        text_len = len(text)
        scan_limit = min(text_len, 256)

        # Generic short-pattern repetition
        max_token_len = 6
        for size in range(1, max_token_len + 1):
            # Minimum text needed for 3 repeats of this size
            min_needed = size * 3
            if scan_limit < min_needed:
                continue

            i = 0
            end_pos = scan_limit - min_needed + 1
            while i < end_pos:
                candidate = text[i : i + size]
                if not candidate.strip():
                    i += 1
                    continue
                repeats = 1
                j = i + size
                while j + size <= text_len and text[j : j + size] == candidate:
                    repeats += 1
                    j += size
                if repeats >= 3:
                    return (candidate, repeats)
                # PERFORMANCE: Skip past the matched repeats (if any),
                # since we already checked those positions implicitly
                i += max(1, repeats * size - size + 1)
        return (None, 0)
    except IndexError as e:
        logger.debug("Error during simple repetition detection: %s", e)
        return (None, 0)


def analyze_complete_response_for_loops(
    response_text: str, loop_detector: LoopDetector | None = None
) -> LoopDetectionEvent | None:
    """
    Analyze a complete response for loops (for non-streaming responses).

    Args:
        response_text: The complete response text to analyze
        loop_detector: The loop detector instance to use

    Returns:
        LoopDetectionEvent if a loop is detected, None otherwise
    """
    if not loop_detector or not loop_detector.is_enabled():
        return None

    # Reset detector state for fresh analysis
    loop_detector.reset()

    # Process the entire response as a single chunk
    return loop_detector.process_chunk(response_text)
