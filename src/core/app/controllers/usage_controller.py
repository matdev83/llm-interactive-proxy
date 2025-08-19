"""
Usage controller for exposing usage tracking endpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from src.core.di.services import get_or_build_service_provider
from src.core.domain.usage_data import UsageData
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
    ) -> dict[str, Any]:
        """Get usage statistics.

        Args:
            project: Optional project filter
            days: Number of days to include in stats

        Returns:
            Usage statistics dictionary
        """
        if not self.usage_service:
            return {"error": "Usage tracking service not available"}

        result = await self.usage_service.get_usage_stats(project=project, days=days)
        return result  # type: ignore[no-any-return]

    async def get_recent_usage(
        self, session_id: str | None = None, limit: int = 100
    ) -> list[UsageData]:
        """Get recent usage data.

        Args:
            session_id: Optional session ID filter
            limit: Maximum number of records to return

        Returns:
            List of usage data entities
        """
        if not self.usage_service:
            return []

        result = await self.usage_service.get_recent_usage(
            session_id=session_id, limit=limit
        )
        return result  # type: ignore[no-any-return]


@router.get("/stats", response_model=dict[str, Any])
async def get_usage_stats(
    project: str | None = Query(None, description="Filter by project name"),
    days: int = Query(30, description="Number of days to include in stats"),
    service_provider: Any = Depends(get_or_build_service_provider),
) -> dict[str, Any]:
    """Get usage statistics.

    Args:
        project: Optional project filter
        days: Number of days to include in stats
        service_provider: Service provider dependency

    Returns:
        Usage statistics dictionary
    """
    usage_service = service_provider.get_required_service(IUsageTrackingService)
    result = await usage_service.get_usage_stats(project=project, days=days)
    return result  # type: ignore[no-any-return]


@router.get("/recent", response_model=list[UsageData])
async def get_recent_usage(
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(100, description="Maximum number of records to return"),
    service_provider: Any = Depends(get_or_build_service_provider),
) -> list[UsageData]:
    """Get recent usage data.

    Args:
        session_id: Optional session ID filter
        limit: Maximum number of records to return
        service_provider: Service provider dependency

    Returns:
        List of usage data entities
    """
    usage_service = service_provider.get_required_service(IUsageTrackingService)
    result = await usage_service.get_recent_usage(session_id=session_id, limit=limit)
    return result  # type: ignore[no-any-return]
