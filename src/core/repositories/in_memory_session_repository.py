from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from src.core.domain.session import Session
from src.core.interfaces.repositories_interface import ISessionRepository

logger = logging.getLogger(__name__)


class InMemorySessionRepository(ISessionRepository):
    """In-memory implementation of session repository.

    This repository keeps sessions in memory and does not persist them.
    It is suitable for development and testing.
    """

    def __init__(self) -> None:
        """Initialize the in-memory session repository."""
        self._sessions: dict[str, Session] = {}
        self._user_sessions: dict[str, list[str]] = {}
        self._last_accessed: dict[str, float] = {}

    async def get_by_id(self, id: str) -> Session | None:
        """Get a session by its ID."""
        session = self._sessions.get(id)
        if session:
            self._last_accessed[id] = time.time()
        return session

    async def get_all(self) -> list[Session]:
        """Get all sessions."""
        return list(self._sessions.values())

    async def add(self, entity: Session) -> Session:
        """Add a new session."""
        self._sessions[entity.id] = entity
        self._last_accessed[entity.id] = self._get_last_active_timestamp(entity)

        # Track by user if available
        if hasattr(entity, "user_id") and entity.user_id:
            if entity.user_id not in self._user_sessions:
                self._user_sessions[entity.user_id] = []
            self._user_sessions[entity.user_id].append(entity.id)

        return entity

    async def update(self, entity: Session) -> Session:
        """Update an existing session."""
        if entity.id not in self._sessions:
            return await self.add(entity)

        self._sessions[entity.id] = entity
        self._last_accessed[entity.id] = self._get_last_active_timestamp(entity)
        return entity

    async def delete(self, id: str) -> bool:
        """Delete a session by its ID."""
        if id in self._sessions:
            session = self._sessions[id]

            # Remove from user tracking if applicable
            if hasattr(session, "user_id") and session.user_id:
                user_id = session.user_id
                if (
                    user_id in self._user_sessions
                    and id in self._user_sessions[user_id]
                ):
                    self._user_sessions[user_id].remove(id)

            # Remove from main collections
            del self._sessions[id]
            if id in self._last_accessed:
                del self._last_accessed[id]

            return True
        return False

    async def get_by_user_id(self, user_id: str) -> list[Session]:
        """Get all sessions for a specific user."""
        session_ids = self._user_sessions.get(user_id, [])
        return [self._sessions[id] for id in session_ids if id in self._sessions]

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        """Clean up expired sessions.

        Args:
            max_age_seconds: Maximum age of sessions to keep in seconds

        Returns:
            The number of sessions deleted
        """
        now = time.time()
        expired_ids = [
            session_id
            for session_id, last_access in self._last_accessed.items()
            if now - last_access > max_age_seconds
        ]

        count = 0
        for session_id in expired_ids:
            if await self.delete(session_id):
                count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} expired sessions")

        return count

    def _get_last_active_timestamp(self, session: Session) -> float:
        """Return the last activity timestamp for a session."""

        last_active: Any = getattr(session, "last_active_at", None)
        if isinstance(last_active, datetime):
            # Ensure timezone-aware datetimes are converted safely
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)
            return last_active.timestamp()

        return time.time()
