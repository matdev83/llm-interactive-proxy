"""Usage tracking interface (suffixed)."""

from __future__ import annotations

import abc
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from src.core.domain.usage_data import UsageData


class IUsageTrackingService(abc.ABC):
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
    ) -> UsageData:
        pass

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
        yield

    @abc.abstractmethod
    async def get_usage_stats(
        self, project: str | None = None, days: int = 30
    ) -> dict[str, Any]:
        pass

    @abc.abstractmethod
    async def get_recent_usage(
        self, session_id: str | None = None, limit: int = 100
    ) -> list[UsageData]:
        pass
