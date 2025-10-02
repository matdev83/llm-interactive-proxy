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
    assert result.repetitions == 3
    assert result.details["pattern_length"] == len(pattern)
    assert result.details["total_repeated_chars"] == len(pattern) * result.repetitions
