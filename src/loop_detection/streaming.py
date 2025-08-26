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
    """
    try:
        # Fast path: common noisy token
        token = "ERROR "
        if token in text:
            count = text.count(token)
            return (token.strip(), count)

        # Generic short-pattern repetition
        max_token_len = 6
        for size in range(1, max_token_len + 1):
            for i in range(min(len(text), 256) - size * 3 + 1):
                candidate = text[i : i + size]
                if not candidate.strip():
                    continue
                repeats = 1
                j = i + size
                while j + size <= len(text) and text[j : j + size] == candidate:
                    repeats += 1
                    j += size
                if repeats >= 3:
                    return (candidate, repeats)
        return (None, 0)
    except Exception:
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
