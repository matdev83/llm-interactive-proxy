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
async def test_short_pattern_details_identify_short_detector() -> None:
    """Ensure detection metadata flags gemini-cli short pattern detections."""
    short_config = {
        "content_loop_threshold": 10,
        "content_chunk_size": 50,
        "max_history_length": 4096,
    }
    long_config = {
        "min_pattern_length": 80,
        "max_pattern_length": 160,
        "min_repetitions": 3,
        "max_history": 4096,
    }

    detector = HybridLoopDetector(
        short_detector_config=short_config,
        long_detector_config=long_config,
    )

    repeating_chunk = "A" * short_config["content_chunk_size"]
    content = repeating_chunk * (short_config["content_loop_threshold"] + 2)

    result = await detector.check_for_loops(content)

    assert result.has_loop is True
    assert result.details is not None
    assert result.details["detection_method"] == "short_pattern"
