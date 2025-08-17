from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.core.domain.session import Session
from src.core.interfaces.repositories import ISessionRepository

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

    async def get_by_id(self, id: str) -> Session | None:
        """Get a session by its ID."""
        return self._sessions.get(id)

    async def get_all(self) -> list[Session]:
        """Get all sessions."""
        return list(self._sessions.values())

    async def add(self, entity: Session) -> Session:
        """Add a new session."""
        self._sessions[entity.session_id] = entity
        # If user ID is provided, track the session by user
        if hasattr(entity, "user_id") and entity.user_id:
            user_id = entity.user_id
            if user_id not in self._user_sessions:
                self._user_sessions[user_id] = []
            self._user_sessions[user_id].append(entity.session_id)
        return entity

    async def update(self, entity: Session) -> Session:
        """Update an existing session."""
        if entity.session_id not in self._sessions:
            return await self.add(entity)

        self._sessions[entity.session_id] = entity
        return entity

    async def delete(self, id: str) -> bool:
        """Delete a session by its ID."""
        if id in self._sessions:
            # Remove from user sessions if applicable
            for _user_id, sessions in self._user_sessions.items():
                if id in sessions:
                    sessions.remove(id)

            # Delete the session
            del self._sessions[id]
            return True
        return False

    async def get_by_user_id(self, user_id: str) -> list[Session]:
        """Get all sessions for a specific user."""
        session_ids = self._user_sessions.get(user_id, [])
        return [self._sessions[id] for id in session_ids if id in self._sessions]

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        """Clean up expired sessions."""
        now = datetime.now(timezone.utc)
        expired_ids = []

        for session_id, session in self._sessions.items():
            last_active = session.last_active_at
            age = (now - last_active).total_seconds()

            if age > max_age_seconds:
                expired_ids.append(session_id)

        # Delete expired sessions
        for session_id in expired_ids:
            await self.delete(session_id)

        return len(expired_ids)


class PersistentSessionRepository(ISessionRepository):
    """Persistent implementation of session repository.

    This repository persists sessions to storage (future implementation).
    It would use file-based storage, a database, or another persistence mechanism.
    """

    def __init__(self, storage_path: str | None = None):
        """Initialize the persistent session repository.

        Args:
            storage_path: Optional path to store sessions
        """
        self._memory_repo = InMemorySessionRepository()  # Use in-memory as cache
        self._storage_path = storage_path
        # Future: Initialize storage adapter based on storage_path

    async def get_by_id(self, id: str) -> Session | None:
        """Get a session by its ID."""
        # First check in-memory cache
        session = await self._memory_repo.get_by_id(id)
        if session:
            return session

        # Future: If not in cache, load from storage
        # session = await self._load_session_from_storage(id)
        # if session:
        #     await self._memory_repo.add(session)
        #     return session

        return None

    async def get_all(self) -> list[Session]:
        """Get all sessions."""
        # Future: Load all sessions from storage, but for now just return in-memory
        return await self._memory_repo.get_all()

    async def add(self, entity: Session) -> Session:
        """Add a new session."""
        # Add to in-memory cache
        await self._memory_repo.add(entity)

        # Future: Persist to storage
        # await self._save_session_to_storage(entity)

        return entity

    async def update(self, entity: Session) -> Session:
        """Update an existing session."""
        # Update in-memory cache
        await self._memory_repo.update(entity)

        # Future: Persist to storage
        # await self._save_session_to_storage(entity)

        return entity

    async def delete(self, id: str) -> bool:
        """Delete a session by its ID."""
        # Delete from in-memory cache
        result = await self._memory_repo.delete(id)

        # Future: Delete from storage
        # if result:
        #     await self._delete_session_from_storage(id)

        return result

    async def get_by_user_id(self, user_id: str) -> list[Session]:
        """Get all sessions for a specific user."""
        # For now, just use the in-memory implementation
        return await self._memory_repo.get_by_user_id(user_id)

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        """Clean up expired sessions."""
        # For now, just use the in-memory implementation
        return await self._memory_repo.cleanup_expired(max_age_seconds)

    # Future methods for storage persistence
    # async def _save_session_to_storage(self, session: Session) -> None:
    #     ...
    #
    # async def _load_session_from_storage(self, id: str) -> Optional[Session]:
    #     ...
    #
    # async def _delete_session_from_storage(self, id: str) -> None:
    #     ...
