"""Usage recording service interface for detailed usage tracking.

This module defines the interface for recording detailed usage metrics
at all four measurement points (verbatim ingress, mutated egress to backend,
verbatim backend response, mutated egress to client).
"""

from __future__ import annotations

import abc
from typing import Any

from src.core.domain.traffic_leg import TrafficLeg


class IUsageRecordingService(abc.ABC):
    """Interface for recording detailed usage metrics.

    This service records usage at all four measurement points to provide
    full observability of traffic before and after proxy mutations.
    """

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
        app_title: str | None = None,
    ) -> str:
        """Record an incoming request and create a usage record.

        This method creates a new UsageRecord with request data and returns
        a record ID that can be used to complete the record with response data.

        Args:
            session_id: Session identifier for grouping related requests
            backend_type: Backend type (e.g., 'openai', 'anthropic', 'gemini')
            model: Model name effectively used
            frontend_type: Frontend type (e.g., 'openai', 'anthropic')
            leg: Traffic leg (CTP, PTB, BTP, PTC)
            prompt_tokens: Number of prompt tokens
            user_agent: User agent string (optional)
            proxy_user: Proxy user identifier (optional)
            app_title: Application title (optional)

        Returns:
            Record ID that can be used to complete the record with response data

        Raises:
            ValueError: If required parameters are invalid
        """

    @abc.abstractmethod
    async def record_response(
        self,
        record_id: str,
        completion_tokens: int,
        http_status_code: int,
        tool_call_count: int = 0,
        tool_names: list[str] | None = None,
        ttft_ms: float | None = None,
        proxy_processing_ms: float = 0.0,
        total_duration_ms: float = 0.0,
        backend_reported_usage: dict[str, Any] | None = None,
    ) -> None:
        """Complete a usage record with response data.

        This method updates an existing UsageRecord with response metrics,
        including timing, tool calls, and backend-reported usage.

        Args:
            record_id: ID of the record to update (from record_request)
            completion_tokens: Number of completion tokens
            http_status_code: HTTP status code from response
            tool_call_count: Number of tool calls in response (default: 0)
            tool_names: Names of tools called (optional)
            ttft_ms: Time to first token in milliseconds (optional)
            proxy_processing_ms: Proxy processing time in milliseconds (default: 0.0)
            total_duration_ms: Total request duration in milliseconds (default: 0.0)
            backend_reported_usage: Backend-reported usage metadata (optional)

        Raises:
            ValueError: If record_id is not found or parameters are invalid
        """
