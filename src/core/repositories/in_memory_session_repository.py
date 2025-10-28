from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from src.core.domain.session import Session
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprintBundle,
)

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
        # Session continuity tracking
        self._fingerprints: dict[str, str] = {}  # session_id -> fingerprint
        self._client_sessions: dict[str, list[str]] = {}  # client_key -> session_ids
        self._fingerprint_bundles: dict[str, ConversationFingerprintBundle] = {}

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

            # Remove from fingerprint tracking
            if id in self._fingerprints:
                del self._fingerprints[id]
            if id in self._fingerprint_bundles:
                del self._fingerprint_bundles[id]

            # Remove from client session tracking
            for client_key, session_ids in list(self._client_sessions.items()):
                if id in session_ids:
                    session_ids.remove(id)
                    if not session_ids:
                        del self._client_sessions[client_key]

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
        now = datetime.now(timezone.utc)
        now_timestamp = time.time()
        expired_ids = []

        for session_id, session in self._sessions.items():
            # Use session's last_active_at if available, otherwise fall back to _last_accessed
            if hasattr(session, "last_active_at") and session.last_active_at:
                last_active = session.last_active_at

                if isinstance(last_active, datetime):
                    if (
                        last_active.tzinfo is None
                        or last_active.tzinfo.utcoffset(last_active) is None
                    ):
                        last_active = last_active.replace(tzinfo=timezone.utc)
                    else:
                        last_active = last_active.astimezone(timezone.utc)

                    age = (now - last_active).total_seconds()
                else:
                    logger.debug(
                        "Session %s has non-datetime last_active_at (%s); falling back to access timestamp",
                        session_id,
                        type(last_active).__name__,
                    )
                    last_access_timestamp = self._last_accessed.get(
                        session_id, now_timestamp
                    )
                    age = now_timestamp - last_access_timestamp
            else:
                # Fall back to internal tracking
                last_access_timestamp = self._last_accessed.get(
                    session_id, now_timestamp
                )
                age = now_timestamp - last_access_timestamp

            if age > max_age_seconds:
                expired_ids.append(session_id)

        count = 0
        for session_id in expired_ids:
            if await self.delete(session_id):
                count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} expired sessions")

        return count

    async def update_fingerprint(self, session_id: str, fingerprint: str) -> None:
        """Update the conversation fingerprint for a session.

        Args:
            session_id: Session ID to update
            fingerprint: New fingerprint value
        """
        self._fingerprints[session_id] = fingerprint
        self._last_accessed[session_id] = time.time()

    async def update_client_session(self, session_id: str, client_key: str) -> None:
        """Track a session as belonging to a specific client.

        Args:
            session_id: Session ID
            client_key: Client identifier (e.g., IP + user-agent hash)
        """
        if client_key not in self._client_sessions:
            self._client_sessions[client_key] = []
        if session_id not in self._client_sessions[client_key]:
            self._client_sessions[client_key].append(session_id)

    async def find_by_client_and_fingerprint(
        self, client_key: str, fingerprint: str
    ) -> Session | None:
        """Find a session by client key and conversation fingerprint.

        Args:
            client_key: Client identifier
            fingerprint: Conversation fingerprint to match

        Returns:
            Session if found, None otherwise
        """
        # Get all sessions for this client
        session_ids = self._client_sessions.get(client_key, [])

        # Check each session for matching fingerprint
        for session_id in session_ids:
            if self._fingerprints.get(session_id) == fingerprint:
                session = self._sessions.get(session_id)
                if session:
                    self._last_accessed[session_id] = time.time()
                    return session

        return None

    async def find_recent_sessions_by_client(
        self, client_key: str, max_age_seconds: int
    ) -> list[Session]:
        """Find recent sessions for a client.

        Args:
            client_key: Client identifier
            max_age_seconds: Maximum age in seconds

        Returns:
            List of recent sessions, ordered by most recent first
        """
        session_ids = self._client_sessions.get(client_key, [])
        now = time.time()

        recent_sessions = []
        for session_id in session_ids:
            last_access = self._last_accessed.get(session_id, 0)
            age = now - last_access

            if age <= max_age_seconds:
                session = self._sessions.get(session_id)
                if session:
                    recent_sessions.append((last_access, session))

        # Sort by last access time (most recent first)
        recent_sessions.sort(key=lambda x: x[0], reverse=True)

        return [session for _, session in recent_sessions]

    async def get_session_fingerprint(self, session_id: str) -> str | None:
        """Get the fingerprint for a session.

        Args:
            session_id: Session ID

        Returns:
            Fingerprint if found, None otherwise
        """
        return self._fingerprints.get(session_id)

    async def update_fingerprint_bundle(
        self, session_id: str, bundle: ConversationFingerprintBundle
    ) -> None:
        """Store extended fingerprint metadata."""
        self._fingerprint_bundles[session_id] = bundle
        self._last_accessed[session_id] = time.time()

    async def get_fingerprint_bundle(
        self, session_id: str
    ) -> ConversationFingerprintBundle | None:
        """Retrieve stored fingerprint metadata."""
        return self._fingerprint_bundles.get(session_id)

    async def get_session_last_access(self, session_id: str) -> float | None:
        """Return the last access timestamp for the session."""
        return self._last_accessed.get(session_id)
