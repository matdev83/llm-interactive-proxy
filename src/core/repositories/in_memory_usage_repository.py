from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from src.core.domain.usage_data import UsageData
from src.core.interfaces.repositories import IUsageRepository

logger = logging.getLogger(__name__)


class InMemoryUsageRepository(IUsageRepository):
    """In-memory implementation of usage repository.

    This repository keeps usage data in memory and does not persist them.
    It is suitable for development and testing.
    """

    def __init__(self):
        """Initialize the in-memory usage repository."""
        self._usage: dict[str, UsageData] = {}
        self._session_usage: dict[str, list[str]] = {}

    async def get_by_id(self, id: str) -> UsageData | None:
        """Get usage data by its ID."""
        return self._usage.get(id)

    async def get_all(self) -> list[UsageData]:
        """Get all usage data."""
        return list(self._usage.values())

    async def add(self, entity: UsageData) -> UsageData:
        """Add new usage data."""
        self._usage[entity.id] = entity
        # Track by session
        if entity.session_id:
            if entity.session_id not in self._session_usage:
                self._session_usage[entity.session_id] = []
            self._session_usage[entity.session_id].append(entity.id)
        return entity

    async def update(self, entity: UsageData) -> UsageData:
        """Update existing usage data."""
        if entity.id not in self._usage:
            return await self.add(entity)

        self._usage[entity.id] = entity
        return entity

    async def delete(self, id: str) -> bool:
        """Delete usage data by its ID."""
        if id in self._usage:
            # Remove from session tracking
            for _session_id, usage_ids in self._session_usage.items():
                if id in usage_ids:
                    usage_ids.remove(id)

            del self._usage[id]
            return True
        return False

    async def get_by_session_id(self, session_id: str) -> list[UsageData]:
        """Get all usage data for a specific session."""
        usage_ids = self._session_usage.get(session_id, [])
        return [self._usage[id] for id in usage_ids if id in self._usage]

    async def get_stats(self, project: str | None = None) -> dict[str, Any]:
        """Get usage statistics, optionally filtered by project."""
        stats: dict[str, Any] = defaultdict(
            lambda: {
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost": 0.0,
                "requests": 0,
            }
        )

        data_to_process = list(self._usage.values())
        if project:
            data_to_process = [u for u in data_to_process if u.project == project]

        for usage in data_to_process:
            model_stats = stats[usage.model]
            model_stats["total_tokens"] += usage.total_tokens
            model_stats["prompt_tokens"] += usage.prompt_tokens
            model_stats["completion_tokens"] += usage.completion_tokens
            if usage.cost:
                model_stats["cost"] += usage.cost
            model_stats["requests"] += 1

        return dict(stats)
