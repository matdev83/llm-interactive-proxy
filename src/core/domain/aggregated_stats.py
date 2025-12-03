"""Aggregated statistics data model for usage tracking.

This module defines the AggregatedStats dataclass which captures summary
metrics aggregated from multiple usage records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.domain.timing_stats import TimingStats


@dataclass
class AggregatedStats:
    """Summary metrics aggregated from multiple usage records.

    Attributes:
        request_count: Total number of requests
        response_count: Total number of responses
        unique_sessions: Number of unique sessions
        total_turns: Total number of turns across all sessions

        total_prompt_tokens: Sum of all prompt tokens
        total_completion_tokens: Sum of all completion tokens
        total_tokens: Sum of all tokens
        tokens_per_session: Average tokens per session

        completion_tokens_per_second: Throughput for completion tokens
        total_tokens_per_second: Throughput for all tokens

        total_tool_calls: Total number of tool calls

        ttft_stats: Time to first token statistics
        proxy_processing_stats: Proxy processing time statistics
        duration_stats: Total duration statistics

        status_code_counts: Breakdown of HTTP status codes
        filters: Filter dimensions applied to generate these stats
        time_window_seconds: Time window for TPS calculation
    """

    # Counts
    request_count: int = 0
    response_count: int = 0
    unique_sessions: int = 0
    total_turns: int = 0

    # Token metrics
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    tokens_per_session: float = 0.0

    # Throughput metrics
    completion_tokens_per_second: float = 0.0
    total_tokens_per_second: float = 0.0

    # Tool metrics
    total_tool_calls: int = 0

    # Timing metrics
    ttft_stats: TimingStats | None = None
    proxy_processing_stats: TimingStats | None = None
    duration_stats: TimingStats | None = None

    # Status code breakdown
    status_code_counts: dict[int, int] = field(default_factory=dict)

    # Breakdown dimensions applied
    filters: dict[str, Any] = field(default_factory=dict)

    # Time window for TPS calculation
    time_window_seconds: float = 0.0
