from __future__ import annotations

import logging

from src.core.domain.session import Session
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprintBundle,
)

logger = logging.getLogger(__name__)


# Import the canonical implementation
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository


class PersistentSessionRepository(ISessionRepository):
    """Persistent implementation of session repository.

    This repository persists sessions to storage (future implementation).
    It would use file-based storage, a database, or another persistence mechanism.
    """

    def __init__(
        self,
        storage_path: str | None = None,
        *,
        max_sessions: int | None = None,
    ):
        """Initialize the persistent session repository.

        Args:
            storage_path: Optional path to store sessions
        """
        self._memory_repo = InMemorySessionRepository(
            max_sessions=max_sessions
        )  # Use in-memory as cache
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

    async def update_fingerprint(self, session_id: str, fingerprint: str) -> None:
        """Update the conversation fingerprint for a session."""
        await self._memory_repo.update_fingerprint(session_id, fingerprint)

    async def update_client_session(self, session_id: str, client_key: str) -> None:
        """Associate a session with a client identifier."""
        await self._memory_repo.update_client_session(session_id, client_key)

    async def find_by_client_and_fingerprint(
        self, client_key: str, fingerprint: str
    ) -> Session | None:
        """Find a session by client key and conversation fingerprint."""
        return await self._memory_repo.find_by_client_and_fingerprint(
            client_key, fingerprint
        )

    async def find_recent_sessions_by_client(
        self, client_key: str, max_age_seconds: int
    ) -> list[Session]:
        """Find recent sessions for a client."""
        return await self._memory_repo.find_recent_sessions_by_client(
            client_key, max_age_seconds
        )

    async def get_session_fingerprint(self, session_id: str) -> str | None:
        """Get the conversation fingerprint for a session."""
        return await self._memory_repo.get_session_fingerprint(session_id)

    async def update_fingerprint_bundle(
        self, session_id: str, bundle: ConversationFingerprintBundle
    ) -> None:
        """Update fingerprint metadata for a session."""
        await self._memory_repo.update_fingerprint_bundle(session_id, bundle)

    async def get_fingerprint_bundle(
        self, session_id: str
    ) -> ConversationFingerprintBundle | None:
        """Get fingerprint metadata for a session."""
        return await self._memory_repo.get_fingerprint_bundle(session_id)

    async def get_session_last_access(self, session_id: str) -> float | None:
        """Get last access timestamp for a session."""
        return await self._memory_repo.get_session_last_access(session_id)

    # Future methods for storage persistence
    # async def _save_session_to_storage(self, session: Session) -> None:
    #     ...
    #
    # async def _load_session_from_storage(self, id: str) -> Optional[Session]:
    #     ...
    #
    # async def _delete_session_from_storage(self, id: str) -> None:
    #     ...
