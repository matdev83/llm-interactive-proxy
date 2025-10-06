from __future__ import annotations

import logging

from src.core.domain.session import Session
from src.core.interfaces.repositories_interface import ISessionRepository

logger = logging.getLogger(__name__)


# Import the canonical implementation
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository


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
