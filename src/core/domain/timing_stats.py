"""Timing statistics data model for usage tracking.

This module defines the TimingStats dataclass which captures statistical
metrics for timing measurements (TTFT, proxy processing time, total duration).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class TimingStats:
    """Statistical metrics for timing measurements.

    Attributes:
        count: Number of timing measurements
        min_ms: Minimum timing value in milliseconds
        max_ms: Maximum timing value in milliseconds
        avg_ms: Average timing value in milliseconds
        p50_ms: 50th percentile (median) in milliseconds
        p95_ms: 95th percentile in milliseconds
        p99_ms: 99th percentile in milliseconds
    """

    count: int
    min_ms: float
    max_ms: float
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float

    @classmethod
    def from_values(cls, values: Sequence[float]) -> TimingStats:
        """Calculate timing statistics from a sequence of timing values.

        Args:
            values: Sequence of timing values in milliseconds

        Returns:
            TimingStats instance with calculated statistics

        Raises:
            ValueError: If values sequence is empty
        """
        if not values:
            raise ValueError("Cannot calculate statistics from empty sequence")

        sorted_values = sorted(values)
        count = len(sorted_values)

        # Calculate basic statistics
        min_val = sorted_values[0]
        max_val = sorted_values[-1]
        avg_val = sum(sorted_values) / count

        # Calculate percentiles
        p50_idx = int(count * 0.50)
        p95_idx = int(count * 0.95)
        p99_idx = int(count * 0.99)

        # Ensure indices are within bounds
        p50_idx = min(p50_idx, count - 1)
        p95_idx = min(p95_idx, count - 1)
        p99_idx = min(p99_idx, count - 1)

        p50_val = sorted_values[p50_idx]
        p95_val = sorted_values[p95_idx]
        p99_val = sorted_values[p99_idx]

        return cls(
            count=count,
            min_ms=min_val,
            max_ms=max_val,
            avg_ms=avg_val,
            p50_ms=p50_val,
            p95_ms=p95_val,
            p99_ms=p99_val,
        )
