"""
Usage tracking service that integrates with the existing llm_accounting_utils functionality.

This service provides a bridge between the new SOLID architecture and the legacy
usage tracking system.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi.responses import StreamingResponse

from src.core.domain.usage_data import UsageData
from src.core.interfaces.repositories_interface import IUsageRepository
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
from src.llm_accounting_utils import (
    is_accounting_disabled,
    track_llm_request,
    track_usage_metrics,
)

logger = logging.getLogger(__name__)


class UsageTrackingService(IUsageTrackingService):
    """Service for tracking LLM usage across the application.

    This service integrates with the existing llm_accounting_utils functionality
    while also storing usage data in the new repository structure.
    """

    def __init__(self, usage_repository: IUsageRepository):
        """Initialize the usage tracking service.

        Args:
            usage_repository: Repository for storing usage data
        """
        self._repository = usage_repository

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
        # Use legacy tracking system
        if not is_accounting_disabled():
            track_usage_metrics(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost=cost,
                execution_time=execution_time,
                backend=backend,
                username=username,
                project=project,
                session=session_id,
                reasoning_tokens=reasoning_tokens,
                cached_tokens=cached_tokens,
            )

        # Create usage data entity
        usage_data = UsageData(
            id=str(uuid.uuid4()),
            session_id=session_id or "unknown",
            project=project,
            model=f"{backend}:{model}" if backend else model,
            prompt_tokens=prompt_tokens or 0,
            completion_tokens=completion_tokens or 0,
            total_tokens=total_tokens or 0,
            cost=cost,
            timestamp=datetime.utcnow(),
        )

        # Store in repository
        await self._repository.add(usage_data)

        return usage_data

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

        This method wraps the legacy track_llm_request context manager while also
        storing usage data in the new repository structure.

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

        class RequestTracker:
            def __init__(self) -> None:
                self.response: dict[str, Any] | StreamingResponse | None = None
                self.response_headers: dict[str, str] = {}
                self.cost = 0.0
                self.remote_completion_id: str | None = None
                self.usage_data: UsageData | None = None

            def set_response(
                self, response: dict[str, Any] | StreamingResponse
            ) -> None:
                """Set the response and extract information."""
                self.response = response

            def set_response_headers(self, headers: dict[str, str]) -> None:
                """Set the response headers for billing extraction."""
                self.response_headers = headers

            def set_cost(self, cost: float) -> None:
                """Set the cost for this request."""
                self.cost = cost

            def set_completion_id(self, completion_id: str) -> None:
                """Set the remote completion ID."""
                self.remote_completion_id = completion_id

            def set_usage_data(self, usage_data: UsageData) -> None:
                """Set the usage data entity."""
                self.usage_data = usage_data

        tracker = RequestTracker()
        start_time = time.time()

        # If accounting is disabled, just yield the tracker
        if is_accounting_disabled():
            try:
                yield tracker
            finally:
                pass
            return

        # Use legacy tracking system
        async with track_llm_request(
            model=model,
            backend=backend,
            messages=messages,
            username=username,
            project=project,
            session=session_id,
            **kwargs,
        ) as legacy_tracker:
            try:
                # Yield our tracker
                yield tracker

                # Copy data from our tracker to legacy tracker
                if tracker.response:
                    legacy_tracker.set_response(tracker.response)
                if tracker.response_headers:
                    legacy_tracker.set_response_headers(tracker.response_headers)
                if tracker.cost:
                    legacy_tracker.set_cost(tracker.cost)
                if tracker.remote_completion_id:
                    legacy_tracker.set_completion_id(tracker.remote_completion_id)
            finally:
                # Calculate execution time
                execution_time = time.time() - start_time

                # Extract information from response
                # response_text = ""
                prompt_tokens = None
                completion_tokens = None
                total_tokens = None
                cost = tracker.cost

                if tracker.response and isinstance(tracker.response, dict):
                    # Extract usage from non-streaming response
                    usage = tracker.response.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")
                    total_tokens = usage.get("total_tokens")

                    # Extract response text
                    # response_text = extract_response_text(tracker.response)

                # Create usage data entity
                usage_data = await self.track_usage(
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost=cost,
                    execution_time=execution_time,
                    backend=backend,
                    username=username,
                    project=project,
                    session_id=session_id,
                )

                # Set usage data in tracker
                tracker.set_usage_data(usage_data)

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
        return await self._repository.get_stats(project)

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
        if session_id:
            data = await self._repository.get_by_session_id(session_id)
        else:
            data = await self._repository.get_all()

        # Sort by timestamp (newest first) and limit
        sorted_data = sorted(data, key=lambda x: x.timestamp, reverse=True)
        return sorted_data[:limit]
