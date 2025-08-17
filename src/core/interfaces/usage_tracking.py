"""
Interface for usage tracking service.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from src.core.domain.usage_data import UsageData


class IUsageTrackingService(abc.ABC):
    """Interface for tracking LLM usage across the application."""

    @abc.abstractmethod
    async def track_usage(
        self,
        model: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        cost: float = 0.0,
        execution_time: float = 0.0,
        backend: str | None = None,
        username: str | None = None,
        project: str | None = None,
        session_id: str | None = None,
        reasoning_tokens: int = 0,
        cached_tokens: int = 0,
    ) -> UsageData:
        """Track usage metrics for an LLM request.

        Args:
            model: The model name
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            total_tokens: Total number of tokens
            cost: Estimated cost
            execution_time: Execution time in seconds
            backend: Backend provider name
            username: Username
            project: Project name
            session_id: Session ID
            reasoning_tokens: Number of reasoning tokens
            cached_tokens: Number of cached tokens

        Returns:
            The created usage data entity
        """

    @abc.abstractmethod
    @asynccontextmanager
    async def track_request(
        self,
        model: str,
        backend: str,
        messages: list[dict[str, Any]],
        username: str | None = None,
        project: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """Context manager to track both usage metrics and audit logs for LLM requests.

        Args:
            model: The model name
            backend: Backend provider name
            messages: The request messages
            username: Username
            project: Project name
            session_id: Session ID
            **kwargs: Additional arguments

        Yields:
            A request tracker object
        """
        yield

    @abc.abstractmethod
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

    @abc.abstractmethod
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
