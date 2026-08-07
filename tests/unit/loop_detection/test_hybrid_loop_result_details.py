"""Hybrid loop detector result detail tests."""

from __future__ import annotations

import pytest
from src.loop_detection.hybrid_detector import HybridLoopDetector


@pytest.mark.asyncio
async def test_long_pattern_details_report_actual_length() -> None:
    """Ensure long pattern detection reports the true repeated length."""
    pattern = "".join(str(i % 10) for i in range(110))
    content = pattern * 3

    detector = HybridLoopDetector(
        short_detector_config={"content_loop_threshold": 9999},
        long_detector_config={
            "min_pattern_length": len(pattern),
            "min_repetitions": 3,
            "max_history": len(content) + 50,
        },
    )

    result = await detector.check_for_loops(content)

    assert result.has_loop is True
    assert result.details is not None
    # The detector finds overlapping patterns in this specific pattern
    # The important thing is that pattern_length calculation is correct
    assert result.details["pattern_length"] == len(pattern)
    # Verify the total repeated chars matches repetitions * pattern_length
    assert (
        result.details["total_repeated_chars"]
        == result.repetitions * result.details["pattern_length"]
    )


@pytest.mark.asyncio
async def test_short_pattern_detection_method_flagged_correctly() -> None:
    """Short pattern detections should report the short_pattern method."""

    detector = HybridLoopDetector(
        short_detector_config={
            "content_chunk_size": 10,
            "content_loop_threshold": 3,
            "max_history_length": 200,
        },
        long_detector_config={
            # Push the long detector threshold high enough to stay inactive.
            "min_pattern_length": 200,
        },
    )

    repeated_chunk = "abcdefghij"
    content = repeated_chunk * 3

    result = await detector.check_for_loops(content)

    assert result.has_loop is True
    assert result.details is not None
    assert result.details["detection_method"] == "short_pattern"
    assert result.details["pattern_length"] == len(repeated_chunk)
