"""Statistics aggregation service for usage tracking.

This module provides the StatisticsAggregationService class which implements
the IStatisticsService interface for computing aggregated statistics from
usage records.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from src.core.domain.aggregated_stats import AggregatedStats
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.timing_stats import TimingStats
from src.core.domain.usage_record import UsageRecord
from src.core.interfaces.statistics_service_interface import IStatisticsService
from src.core.services.in_memory_usage_store import InMemoryUsageStore

logger = logging.getLogger(__name__)


class StatisticsAggregationService(IStatisticsService):
    """Service for aggregating usage statistics.

    This service computes summary statistics from usage records stored in
    the InMemoryUsageStore, with support for multi-dimensional filtering
    and rolling time windows.

    Attributes:
        _store: In-memory usage store containing usage records
    """

    def __init__(self, store: InMemoryUsageStore):
        """Initialize the statistics aggregation service.

        Args:
            store: In-memory usage store to query for records
        """
        self._store = store

    async def get_aggregated_stats(
        self,
        filters: StatisticsFilter | None = None,
    ) -> AggregatedStats:
        """Get aggregated statistics with optional filters.

        Args:
            filters: Optional filter to apply. If None, aggregates all records.

        Returns:
            AggregatedStats containing summary metrics

        Raises:
            ValueError: If filter parameters are invalid
        """
        # Get filtered records
        records = self._store.get_records(filters)

        # Compute aggregated statistics
        return self._compute_stats(records, filters)

    async def get_rolling_window_stats(
        self,
        window_minutes: int,
        filters: StatisticsFilter | None = None,
    ) -> AggregatedStats:
        """Get statistics for a rolling time window.

        Args:
            window_minutes: Size of the rolling window in minutes
            filters: Optional filter to apply to records in the window

        Returns:
            AggregatedStats for the specified time window

        Raises:
            ValueError: If window_minutes is not positive or filters are invalid
        """
        if window_minutes <= 0:
            raise ValueError(f"window_minutes must be positive, got {window_minutes}")

        # Create a filter with time window
        window_start = datetime.now() - timedelta(minutes=window_minutes)

        # Combine with existing filters
        if filters is None:
            window_filter = StatisticsFilter(start_date=window_start)
        else:
            # Create a new filter with the time window
            window_filter = StatisticsFilter(
                backend_type=filters.backend_type,
                model=filters.model,
                frontend_type=filters.frontend_type,
                leg=filters.leg,
                user_agent=filters.user_agent,
                proxy_user=filters.proxy_user,
                start_date=window_start,
                end_date=filters.end_date,
                day_of_week=filters.day_of_week,
                hour_of_day=filters.hour_of_day,
                http_status_code=filters.http_status_code,
            )

        # Get filtered records
        records = self._store.get_records(window_filter)

        # Compute statistics with time window
        stats = self._compute_stats(records, window_filter)
        stats.time_window_seconds = window_minutes * 60.0

        return stats

    async def get_status_code_breakdown(
        self,
        filters: StatisticsFilter | None = None,
    ) -> dict[str, dict[int, int]]:
        """Get status code counts by backend:model.

        Args:
            filters: Optional filter to apply to records

        Returns:
            Dictionary mapping "backend:model" to status code counts

        Raises:
            ValueError: If filter parameters are invalid
        """
        # Get filtered records
        records = self._store.get_records(filters)

        # Build breakdown
        breakdown: dict[str, dict[int, int]] = {}

        for record in records:
            if record.http_status_code is None:
                continue

            key = f"{record.backend_type}:{record.model}"
            if key not in breakdown:
                breakdown[key] = {}

            status_code = record.http_status_code
            breakdown[key][status_code] = breakdown[key].get(status_code, 0) + 1

        return breakdown

    def _compute_stats(
        self,
        records: list[UsageRecord],
        filters: StatisticsFilter | None,
    ) -> AggregatedStats:
        """Compute aggregated statistics from a list of records.

        Args:
            records: List of usage records to aggregate
            filters: Filter that was applied (for metadata)

        Returns:
            AggregatedStats containing summary metrics
        """
        if not records:
            # Return empty stats
            return AggregatedStats(
                filters=self._filters_to_dict(filters),
            )

        # Count metrics
        request_count = len(records)
        response_count = sum(1 for r in records if r.http_status_code is not None)

        # Session metrics
        unique_sessions = len({r.session_id for r in records})
        total_turns = sum(r.turn_number for r in records)

        # Token metrics
        total_prompt_tokens = sum(r.mutated_prompt_tokens for r in records)
        total_completion_tokens = sum(r.mutated_completion_tokens for r in records)
        total_tokens = sum(r.total_tokens for r in records)

        # Calculate tokens per session
        tokens_per_session = (
            total_tokens / unique_sessions if unique_sessions > 0 else 0.0
        )

        # Tool metrics
        total_tool_calls = sum(r.tool_call_count for r in records)

        # Timing metrics
        ttft_stats = self._compute_timing_stats(
            [r.ttft_ms for r in records if r.ttft_ms is not None]
        )
        proxy_processing_stats = self._compute_timing_stats(
            [r.proxy_processing_ms for r in records if r.proxy_processing_ms > 0]
        )
        duration_stats = self._compute_timing_stats(
            [r.total_duration_ms for r in records if r.total_duration_ms > 0]
        )

        # Status code breakdown
        status_code_counts: dict[int, int] = {}
        for record in records:
            if record.http_status_code is not None:
                status_code = record.http_status_code
                status_code_counts[status_code] = (
                    status_code_counts.get(status_code, 0) + 1
                )

        # Calculate throughput (TPS)
        # For rolling windows, we use the time_window_seconds
        # For non-windowed queries, we calculate from first to last record
        time_window_seconds = 0.0
        completion_tokens_per_second = 0.0
        total_tokens_per_second = 0.0

        if len(records) > 1:
            # Calculate time span from first to last record
            timestamps = sorted(r.timestamp for r in records)
            time_span = (timestamps[-1] - timestamps[0]).total_seconds()

            if time_span > 0:
                time_window_seconds = time_span
                completion_tokens_per_second = total_completion_tokens / time_span
                total_tokens_per_second = total_tokens / time_span

        return AggregatedStats(
            request_count=request_count,
            response_count=response_count,
            unique_sessions=unique_sessions,
            total_turns=total_turns,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_tokens=total_tokens,
            tokens_per_session=tokens_per_session,
            completion_tokens_per_second=completion_tokens_per_second,
            total_tokens_per_second=total_tokens_per_second,
            total_tool_calls=total_tool_calls,
            ttft_stats=ttft_stats,
            proxy_processing_stats=proxy_processing_stats,
            duration_stats=duration_stats,
            status_code_counts=status_code_counts,
            filters=self._filters_to_dict(filters),
            time_window_seconds=time_window_seconds,
        )

    def _compute_timing_stats(self, values: list[float]) -> TimingStats | None:
        """Compute timing statistics from a list of timing values.

        Args:
            values: List of timing values in milliseconds

        Returns:
            TimingStats if values is non-empty, None otherwise
        """
        if not values:
            return None

        try:
            return TimingStats.from_values(values)
        except ValueError:
            return None

    def _filters_to_dict(self, filters: StatisticsFilter | None) -> dict[str, Any]:
        """Convert filters to a dictionary for metadata.

        Args:
            filters: Filter to convert

        Returns:
            Dictionary representation of the filter
        """
        if filters is None:
            return {}

        result: dict[str, Any] = {}

        if filters.backend_type is not None:
            result["backend_type"] = filters.backend_type
        if filters.model is not None:
            result["model"] = filters.model
        if filters.frontend_type is not None:
            result["frontend_type"] = filters.frontend_type
        if filters.leg is not None:
            result["leg"] = filters.leg.value
        if filters.user_agent is not None:
            result["user_agent"] = filters.user_agent
        if filters.proxy_user is not None:
            result["proxy_user"] = filters.proxy_user
        if filters.start_date is not None:
            result["start_date"] = filters.start_date.isoformat()
        if filters.end_date is not None:
            result["end_date"] = filters.end_date.isoformat()
        if filters.day_of_week is not None:
            result["day_of_week"] = filters.day_of_week
        if filters.hour_of_day is not None:
            result["hour_of_day"] = filters.hour_of_day
        if filters.http_status_code is not None:
            result["http_status_code"] = filters.http_status_code

        return result
