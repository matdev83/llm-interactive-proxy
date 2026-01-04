"""Pydantic models for UsageRepository return types."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RepositoryAggregatedStats(BaseModel):
    """Aggregated statistics returned by UsageRepository."""

    request_count: int = 0
    response_count: int = 0
    unique_sessions: int = 0
    total_turns: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    min_ttft: float | None = None
    max_ttft: float | None = None
    avg_ttft: float | None = None
    min_proxy_processing: float | None = None
    max_proxy_processing: float | None = None
    avg_proxy_processing: float | None = None
    min_duration: float | None = None
    max_duration: float | None = None
    avg_duration: float | None = None


class RepositoryUsageStats(BaseModel):
    """Usage statistics for a frontend or backend instance."""

    total_requests: int = 0
    successful_requests: int = 0
    tokens_sent: int = 0
    tokens_received: int = 0
