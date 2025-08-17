from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.session import Session


class ISessionService(ABC):
    """Interface for session management operations.

    This interface defines the contract for components that manage user sessions,
    including creation, retrieval, and updates.
    """

    @abstractmethod
    async def get_session(self, session_id: str) -> Session:
        """Get or create a session for the given session ID.

        Args:
            session_id: The unique identifier for the session

        Returns:
            The session object
        """

    @abstractmethod
    async def update_session(self, session: Session) -> None:
        """Update a session with new data.

        Args:
            session: The session to update
        """

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: The unique identifier for the session to delete

        Returns:
            True if the session was deleted, False if it didn't exist
        """

    @abstractmethod
    async def get_all_sessions(self) -> list[Session]:
        """Get all active sessions.

        Returns:
            A list of all active sessions
        """
