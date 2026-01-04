"""Simulation domain models."""

from __future__ import annotations

from src.core.domain.base import ValueObject


class SimulatorStatistics(ValueObject):
    """Statistics for the backend simulator."""

    total_requests: int
    matched_requests: int
    remaining_requests: int
    streaming_responses: int
    elapsed_time: float

    def __getitem__(self, key: str) -> object:
        """Allow dictionary-like access for backward compatibility."""
        return getattr(self, key)
