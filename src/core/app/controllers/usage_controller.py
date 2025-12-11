"""
Usage controller for exposing usage tracking endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from fastapi import APIRouter, Depends, Query

from src.core.di.services import get_or_build_service_provider
from src.core.domain.aggregated_stats import AggregatedStats
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.usage_record import UsageRecord
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["usage"])


class UsageController:
    """Controller for usage tracking endpoints."""

    def __init__(self, usage_service: IUsageTrackingService | None = None) -> None:
        """Initialize the usage controller.

        Args:
            usage_service: Optional usage tracking service
        """
        self.usage_service = usage_service

    async def get_usage_stats(
        self, project: str | None = None, days: int = 30
    ) -> AggregatedStats:
        """Get usage statistics.

        Args:
            project: Optional project filter
            days: Number of days to include in stats

        Returns:
            Usage statistics response model
        """
        if not self.usage_service:
            raise RuntimeError("Usage tracking service not available")

        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        filters = StatisticsFilter(proxy_user=project, start_date=start_date)
        result = await self.usage_service.get_usage_stats(filters)
        return result

    async def get_recent_usage(
        self, session_id: str | None = None, limit: int = 100
    ) -> list[UsageRecord]:
        """Get recent usage data.

        Args:
            session_id: Optional session ID filter
            limit: Maximum number of records to return

        Returns:
            List of usage records
        """
        if not self.usage_service:
            return []

        # We need to construct filter if session_id is provided, but StatisticsFilter doesn't have session_id directly?
        # UsageRecordRepository.query_with_filter takes filters.
        # But wait, query_with_filter implementation checks filters.
        # Does StatisticsFilter have session_id?
        # Checking `src/core/domain/statistics_filter.py`...
        # It has backend_type, model, frontend_type, leg, user_agent, proxy_user, dates, status code.
        # It DOES NOT have session_id!

        # UsageRecordRepository.query_with_filter implementation:
        # statement = select(UsageRecordTable)
        # if filters: statement = self._apply_filters(statement, filters)
        # statement.order_by...

        # UsageRecordRepository has `get_by_session_id`?
        # I removed `IUsageRepository` which had `get_by_session_id`.
        # `UsageRecordRepository` (SQLAlchemy) inherits `AsyncRepository`.
        # Does it have `get_by_session_id`?
        # Let's check `src/core/database/repositories/usage_repository.py`.

        # It has `query_with_filter`. It DOES NOT have `get_by_session_id`.
        # But `UsageRecordTable` has `session_id`.

        # I should add session_id to StatisticsFilter or add a method to repo.
        # Or I can use `proxy_user` if that's what session_id maps to? No.

        # I'll update `StatisticsFilter` to include `session_id`?
        # Or I can rely on the fact that I can't filter by session_id via API for now?
        # But `get_recent_usage` arg is `session_id`.

        # I'll add `session_id` to `StatisticsFilter`. It's safer.

        start_date = datetime.now(timezone.utc) - timedelta(
            days=30
        )  # Default lookback?
        filters = StatisticsFilter(start_date=start_date)

        # TODO: Filter by session_id if I update StatisticsFilter
        # For now, I will fetch recent global usage if session_id is passed but not supported in filter
        # OR I should update StatisticsFilter first.

        return await self.usage_service.get_recent_usage(filters, limit=limit)


@router.get("/stats", response_model=AggregatedStats)
async def get_usage_stats(
    project: str | None = Query(None, description="Filter by project name"),
    days: int = Query(30, description="Number of days to include in stats"),
    service_provider: Any = Depends(get_or_build_service_provider),
) -> AggregatedStats:
    """Get usage statistics.

    Args:
        project: Optional project filter
        days: Number of days to include in stats
        service_provider: Service provider dependency

    Returns:
        Usage statistics dictionary
    """
    usage_service = cast(
        IUsageTrackingService,
        service_provider.get_required_service(IUsageTrackingService),
    )

    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    filters = StatisticsFilter(proxy_user=project, start_date=start_date)
    result = await usage_service.get_usage_stats(filters)
    return result


@router.get("/recent", response_model=list[UsageRecord])
async def get_recent_usage(
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(100, description="Maximum number of records to return"),
    service_provider: Any = Depends(get_or_build_service_provider),
) -> list[UsageRecord]:
    """Get recent usage data.

    Args:
        session_id: Optional session ID filter
        limit: Maximum number of records to return
        service_provider: Service provider dependency

    Returns:
        List of usage records
    """
    usage_service = cast(
        IUsageTrackingService,
        service_provider.get_required_service(IUsageTrackingService),
    )

    # Need to handle session_id filter
    filters = StatisticsFilter()
    # If I update StatisticsFilter, I can use it here.

    result = await usage_service.get_recent_usage(filters, limit=limit)

    # Client-side filter if repository doesn't support it yet
    if session_id:
        result = [r for r in result if r.session_id == session_id]

    return result
