"""
Pydantic models for usage route responses.
"""

from __future__ import annotations

from typing import Any

from src.core.interfaces.model_bases import DomainModel


class TimingStatsModel(DomainModel):
    """Pydantic version of TimingStats for API responses."""

    count: int
    min_ms: float
    max_ms: float
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


class UsageStatisticsResponse(DomainModel):
    """Response model for aggregated usage statistics."""

    request_count: int
    response_count: int
    unique_sessions: int
    total_turns: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    tokens_per_session: float
    completion_tokens_per_second: float
    total_tokens_per_second: float
    total_tool_calls: int
    status_code_counts: dict[int, int]
    filters: dict[str, Any]
    time_window_seconds: float
    ttft_stats: TimingStatsModel | None = None
    proxy_processing_stats: TimingStatsModel | None = None
    duration_stats: TimingStatsModel | None = None


class RecentUsageResponse(DomainModel):
    """Response model for recent usage records."""

    records: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class UsageExportResponse(DomainModel):
    """Response model for exported usage data."""

    version: int
    exported_at: str
    record_count: int
    filters: dict[str, Any]
    records: list[dict[str, Any]]
