from __future__ import annotations

import logging
import time

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
        self._last_accessed[entity.id] = time.time()

        # Track by user if available
        if hasattr(entity, "user_id") and entity.user_id:
            if entity.user_id not in self._user_sessions:
                self._user_sessions[entity.user_id] = []
            self._user_sessions[entity.user_id].append(entity.id)

        return entity

    async def update(self, entity: Session) -> Session:
        """Update an existing session."""
        existing_session = self._sessions.get(entity.id)
        if existing_session is None:
            return await self.add(entity)

        previous_user_id = next(
            (
                user_id
                for user_id, session_ids in self._user_sessions.items()
                if entity.id in session_ids
            ),
            None,
        )
        new_user_id = getattr(entity, "user_id", None)

        self._sessions[entity.id] = entity
        self._last_accessed[entity.id] = time.time()

        if previous_user_id and previous_user_id != new_user_id:
            tracked_sessions = self._user_sessions.get(previous_user_id)
            if tracked_sessions and entity.id in tracked_sessions:
                tracked_sessions.remove(entity.id)
                if not tracked_sessions:
                    del self._user_sessions[previous_user_id]

        if new_user_id:
            tracked_sessions = self._user_sessions.setdefault(new_user_id, [])
            if entity.id not in tracked_sessions:
                tracked_sessions.append(entity.id)

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
