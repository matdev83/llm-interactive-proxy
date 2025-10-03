"""
Usage tracking service that integrates with the existing llm_accounting_utils functionality.

This service integrates usage tracking with the new SOLID architecture.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
            cost = tracker.cost

            # Extract from headers first if available
            if tracker.response_headers:
                billing = extract_billing_info_from_headers(
                    tracker.response_headers, backend
                )
                usage_details = billing.get("usage", {})
                header_prompt_tokens = usage_details.get("prompt_tokens")
                header_completion_tokens = usage_details.get("completion_tokens")
                header_total_tokens = usage_details.get("total_tokens")

                if prompt_tokens is None and header_prompt_tokens is not None:
                    prompt_tokens = header_prompt_tokens
                if completion_tokens is None and header_completion_tokens is not None:
                    completion_tokens = header_completion_tokens
                if total_tokens is None and header_total_tokens is not None:
                    total_tokens = header_total_tokens

            # Extract from response body
            if tracker.response is not None:
                billing = extract_billing_info_from_response(tracker.response, backend)
                usage_details = billing.get("usage", {})
                response_prompt_tokens = usage_details.get("prompt_tokens")
                response_completion_tokens = usage_details.get("completion_tokens")
                response_total_tokens = usage_details.get("total_tokens")

                if prompt_tokens is None and response_prompt_tokens is not None:
                    prompt_tokens = response_prompt_tokens
                if completion_tokens is None and response_completion_tokens is not None:
                    completion_tokens = response_completion_tokens
                if total_tokens is None and response_total_tokens is not None:
                    total_tokens = response_total_tokens

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
