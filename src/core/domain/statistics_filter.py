"""Statistics filter data model for usage tracking.

This module defines the StatisticsFilter dataclass which specifies filter
criteria for querying usage records and generating aggregated statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord


@dataclass
class StatisticsFilter:
    """Filter criteria for querying usage records.

    Supports filtering by multiple dimensions including backend, model,
    frontend, traffic leg, user context, and date/time ranges.

    Attributes:
        backend_type: Filter by backend type (e.g., 'openai', 'anthropic')
        model: Filter by model name
        frontend_type: Filter by frontend type
        leg: Filter by traffic leg (CTP, PTB, BTP, PTC)
        user_agent: Filter by user agent string
        proxy_user: Filter by proxy user identifier

        start_date: Filter records on or after this date
        end_date: Filter records on or before this date
        day_of_week: Filter by day of week (0=Monday, 6=Sunday)
        hour_of_day: Filter by hour of day (0-23)

        http_status_code: Filter by HTTP status code
    """

    backend_type: str | None = None
    model: str | None = None
    frontend_type: str | None = None
    leg: TrafficLeg | None = None
    user_agent: str | None = None
    proxy_user: str | None = None

    # Date/time filters
    start_date: datetime | None = None
    end_date: datetime | None = None
    day_of_week: int | None = None  # 0=Monday, 6=Sunday
    hour_of_day: int | None = None  # 0-23

    # Status code filter
    http_status_code: int | None = None

    def matches(self, record: UsageRecord) -> bool:
        """Check if a usage record matches this filter.

        Args:
            record: Usage record to check

        Returns:
            True if the record matches all specified filter criteria
        """
        # Backend type filter
        if self.backend_type is not None and record.backend_type != self.backend_type:
            return False

        # Model filter
        if self.model is not None and record.model != self.model:
            return False

        # Frontend type filter
        if (
            self.frontend_type is not None
            and record.frontend_type != self.frontend_type
        ):
            return False

        # Traffic leg filter
        if self.leg is not None and record.leg != self.leg:
            return False

        # User agent filter
        if self.user_agent is not None and record.user_agent != self.user_agent:
            return False

        # Proxy user filter
        if self.proxy_user is not None and record.proxy_user != self.proxy_user:
            return False

        # Date range filters
        if self.start_date is not None and record.timestamp < self.start_date:
            return False

        if self.end_date is not None and record.timestamp > self.end_date:
            return False

        # Day of week filter
        if (
            self.day_of_week is not None
            and record.timestamp.weekday() != self.day_of_week
        ):
            return False

        # Hour of day filter
        if self.hour_of_day is not None and record.timestamp.hour != self.hour_of_day:
            return False

        # HTTP status code filter
        return (
            self.http_status_code is None
            or record.http_status_code == self.http_status_code
        )
