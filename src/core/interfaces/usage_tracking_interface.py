"""Usage tracking interface."""

from __future__ import annotations

import abc
from typing import Any

from src.core.domain.aggregated_stats import AggregatedStats
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord


class IUsageTrackingService(abc.ABC):
    @abc.abstractmethod
    async def record_request(
        self,
        session_id: str,
        backend_type: str,
        model: str,
        frontend_type: str,
        leg: TrafficLeg,
        prompt_tokens: int,
        user_agent: str | None = None,
        proxy_user: str | None = None,
        turn_number: int = 1,
    ) -> str:
        """Record an incoming request (or leg start), returns record_id.

        This method is called when a traffic leg starts (e.g. request received,
        request sent to backend). It records the initial metrics like prompt tokens.
        """

    @abc.abstractmethod
    async def record_response(
        self,
        record_id: str,
        completion_tokens: int,
        http_status_code: int | None = None,
        tool_call_count: int = 0,
        tool_names: list[str] | None = None,
        ttft_ms: float | None = None,
        stream_tps: float | None = None,
        backend_wait_ms: float | None = None,
        proxy_processing_ms: float = 0,
        total_duration_ms: float = 0,
        backend_reported_prompt_tokens: int | None = None,
        backend_reported_completion_tokens: int | None = None,
        backend_reported_cost: float | None = None,
        backend_reported_usage: dict[str, Any] | None = None,
    ) -> None:
        """Complete a usage record with response data.

        This method is called when a traffic leg completes (e.g. response received,
        response sent to client). It updates the record with completion metrics.
        """

    @abc.abstractmethod
    async def get_usage_stats(
        self,
        filters: StatisticsFilter,
    ) -> AggregatedStats:
        """Get aggregated statistics with optional filters."""

    @abc.abstractmethod
    async def get_recent_usage(
        self,
        filters: StatisticsFilter | None = None,
        limit: int = 100,
    ) -> list[UsageRecord]:
        """Get recent usage records."""
