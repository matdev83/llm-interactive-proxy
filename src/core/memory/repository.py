"""Repository interface and implementation for ProxyMem data persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.core.memory.models import SessionSummary


class IMemoryRepository(Protocol):
    """Interface for memory data persistence."""

    async def initialize_schema(self) -> None:
        """Create database schema if it doesn't exist."""
        ...

    async def save_session_summary(self, summary: SessionSummary) -> None:
        """Persist a session summary to the database."""
        ...

    async def get_recent_sessions(
        self,
        user_id: str,
        limit: int,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
    ) -> list[SessionSummary]:
        """Retrieve recent session summaries for a user."""
        ...

    async def delete_old_sessions(self, before_date: datetime) -> int:
        """Delete sessions older than the specified date. Returns count deleted."""
        ...

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        """Get or create a stable project_id for a user+project_root pair."""
        ...
