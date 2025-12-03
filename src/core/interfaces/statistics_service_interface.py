"""Statistics service interface for usage tracking.

This module defines the interface for aggregating and querying usage statistics
with support for multi-dimensional filtering and rolling time windows.
"""

from __future__ import annotations

import abc

from src.core.domain.aggregated_stats import AggregatedStats
from src.core.domain.statistics_filter import StatisticsFilter


class IStatisticsService(abc.ABC):
    """Interface for aggregating and querying usage statistics.

    This service provides methods for computing aggregated statistics from
    usage records with support for filtering by multiple dimensions and
    rolling time windows.
    """

    @abc.abstractmethod
    async def get_aggregated_stats(
        self,
        filters: StatisticsFilter | None = None,
    ) -> AggregatedStats:
        """Get aggregated statistics with optional filters.

        This method computes summary statistics from all usage records that
        match the specified filter criteria. If no filter is provided, it
        aggregates across all records.

        Args:
            filters: Optional filter to apply. If None, aggregates all records.

        Returns:
            AggregatedStats containing summary metrics

        Raises:
            ValueError: If filter parameters are invalid
        """

    @abc.abstractmethod
    async def get_rolling_window_stats(
        self,
        window_minutes: int,
        filters: StatisticsFilter | None = None,
    ) -> AggregatedStats:
        """Get statistics for a rolling time window.

        This method computes statistics for records within a rolling time
        window ending at the current time. Common window sizes are 1, 5,
        and 60 minutes.

        Args:
            window_minutes: Size of the rolling window in minutes
            filters: Optional filter to apply to records in the window

        Returns:
            AggregatedStats for the specified time window

        Raises:
            ValueError: If window_minutes is not positive or filters are invalid
        """

    @abc.abstractmethod
    async def get_status_code_breakdown(
        self,
        filters: StatisticsFilter | None = None,
    ) -> dict[str, dict[int, int]]:
        """Get status code counts by backend:model.

        This method provides a breakdown of HTTP status codes grouped by
        backend type and model name. The returned structure is:
        {
            "backend:model": {
                200: count,
                400: count,
                ...
            },
            ...
        }

        Args:
            filters: Optional filter to apply to records

        Returns:
            Dictionary mapping "backend:model" to status code counts

        Raises:
            ValueError: If filter parameters are invalid
        """
