"""
Session Migration Service

Handles the migration of session data between different versions of the SOLID architecture.
This service provides utilities for converting between different session formats.
"""

from __future__ import annotations

import logging

from src.core.domain.session import Session
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


def create_session_migration_service(
    session_service: ISessionService,
) -> SessionMigrationService:
    """Create a session migration service instance.

    Args:
        session_service: The session service implementation

    Returns:
        A new session migration service instance
    """
    return SessionMigrationService(session_service)


class SessionMigrationService:
    """Service for migrating sessions between different versions."""

    def __init__(self, session_service: ISessionService) -> None:
        """Initialize the migration service.

        Args:
            session_service: The session service implementation
        """
        self._session_service = session_service

    async def migrate_session(
        self, old_session: Session, new_format_version: str
    ) -> Session:
        """Migrate a session to a new format version.

        Args:
            old_session: The session to migrate
            new_format_version: The target format version

        Returns:
            A new session with migrated data
        """
        logger.debug(
            f"Migrating session {old_session.session_id} to format version {new_format_version}"
        )

        # For now, we just return the session as is since we don't have multiple versions yet
        # In the future, we can add version-specific migration logic here
        return old_session

    async def get_or_create_session(self, session_id: str | None = None) -> Session:
        """Get or create a session.

        Args:
            session_id: The session ID to get or create

        Returns:
            A session object
        """
        logger.debug(f"Getting or creating session: {session_id}")

        # Simply delegate to the session service
        return await self._session_service.get_or_create_session(session_id)

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID.

        Args:
            session_id: The session ID to get

        Returns:
            The session if found, None otherwise
        """
        logger.debug(f"Getting session: {session_id}")

        # Simply delegate to the session service
        return await self._session_service.get_session(session_id)

    def _get_session_type(self, session: Session) -> str:
        """Get the type of a session.

        Args:
            session: The session to check

        Returns:
            The session type as a string
        """
        return "new"
