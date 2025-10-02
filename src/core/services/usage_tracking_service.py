"""
Usage tracking service that integrates with the existing llm_accounting_utils functionality.

This service integrates usage tracking with the new SOLID architecture.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


# Define a protocol for objects that behave like StreamingResponse
class StreamingResponseLike(Protocol):
    """Protocol for objects that behave like StreamingResponse."""

    @property
    def body_iterator(self) -> AsyncGenerator[bytes, None]: ...

    @property
    def headers(self) -> dict[str, str]: ...

    @property
    def media_type(self) -> str: ...


from src.core.domain.usage_data import UsageData
from src.core.interfaces.repositories_interface import IUsageRepository
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
from src.llm_accounting_utils import (
    extract_billing_info_from_headers,
    extract_billing_info_from_response,
    is_accounting_disabled,
)

logger = logging.getLogger(__name__)


class UsageTrackingService(IUsageTrackingService):
    """Service for tracking LLM usage across the application.

    This service integrates with the existing llm_accounting_utils functionality
    while also storing usage data in the new repository structure.
    """

    def __init__(self, usage_repository: IUsageRepository) -> None:
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

        Returns:
            The created usage data entity
        """
        # Compute totals if missing
        if (
            total_tokens is None
            and prompt_tokens is not None
            and completion_tokens is not None
        ):
            total_tokens = prompt_tokens + completion_tokens

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
            timestamp=datetime.now(timezone.utc),
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
                self.response: dict[str, Any] | StreamingResponseLike | None = None
                self.response_headers: dict[str, str] = {}
                self.cost = 0.0
                self.remote_completion_id: str | None = None
                self.usage_data: UsageData | None = None
                self.cost_overridden = False

            def set_response(
                self, response: dict[str, Any] | StreamingResponseLike
            ) -> None:
                """Set the response and extract information."""
                self.response = response

            def set_response_headers(self, headers: dict[str, str]) -> None:
                """Set the response headers for billing extraction."""
                self.response_headers = headers

            def set_cost(self, cost: float) -> None:
                """Set the cost for this request."""
                self.cost = cost
                self.cost_overridden = True

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

        # DI-managed accounting (no legacy context manager)
        try:
            # Yield our tracker to allow the caller to set response info
            yield tracker
        finally:
            # Calculate execution time
            execution_time = time.time() - start_time

            prompt_tokens = None
            completion_tokens = None
            total_tokens = None
            derived_cost: float | None = (
                tracker.cost if tracker.cost_overridden else None
            )

            # Extract from headers first if available
            if tracker.response_headers:
                billing = extract_billing_info_from_headers(
                    tracker.response_headers, backend
                )
                u = billing.get("usage", {})
                prompt_tokens = prompt_tokens or u.get("prompt_tokens")
                completion_tokens = completion_tokens or u.get("completion_tokens")
                total_tokens = total_tokens or u.get("total_tokens")
                if not tracker.cost_overridden:
                    header_cost = self._parse_billing_cost(billing.get("cost"))
                    if header_cost is not None:
                        derived_cost = header_cost

            # Extract from response body
            if tracker.response is not None:
                billing = extract_billing_info_from_response(tracker.response, backend)
                u = billing.get("usage", {})
                prompt_tokens = prompt_tokens or u.get("prompt_tokens")
                completion_tokens = completion_tokens or u.get("completion_tokens")
                total_tokens = total_tokens or u.get("total_tokens")
                if not tracker.cost_overridden:
                    response_cost = self._parse_billing_cost(billing.get("cost"))
                    if response_cost is not None:
                        derived_cost = response_cost

            cost = (
                tracker.cost
                if tracker.cost_overridden
                else derived_cost if derived_cost is not None else tracker.cost
            )
            if not tracker.cost_overridden and derived_cost is not None:
                tracker.cost = cost

            # Persist usage data
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
            tracker.set_usage_data(usage_data)

    @staticmethod
    def _parse_billing_cost(value: Any) -> float | None:
        """Parse a billing cost value into a float if valid."""

        if value is None:
            return None
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            logger.debug("Ignoring invalid billing cost value: %s", value, exc_info=True)
            return None
        if math.isnan(candidate) or math.isinf(candidate):
            logger.debug(
                "Ignoring non-finite billing cost value: %s", value, exc_info=True
            )
            return None
        return candidate
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
        if days <= 0:
            logger.warning(
                "Received non-positive days=%s when requesting usage stats; "
                "falling back to complete history.",
                days,
            )
            return await self._repository.get_stats(project)

        usage_records = await self._repository.get_all()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        stats: dict[str, dict[str, Any]] = {}
        project_filter = project

        for usage in usage_records:
            if project_filter is not None and usage.project != project_filter:
                continue

            usage_timestamp = usage.timestamp
            if usage_timestamp.tzinfo is None:
                usage_timestamp = usage_timestamp.replace(tzinfo=timezone.utc)

            if usage_timestamp < cutoff:
                continue

            model_stats = stats.setdefault(
                usage.model,
                {
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost": 0.0,
                    "requests": 0,
                },
            )

            model_stats["total_tokens"] += usage.total_tokens
            model_stats["prompt_tokens"] += usage.prompt_tokens
            model_stats["completion_tokens"] += usage.completion_tokens

            if usage.cost is not None:
                model_stats["cost"] += usage.cost

            model_stats["requests"] += 1

        return stats

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
