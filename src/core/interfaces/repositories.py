from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from src.core.domain.session import Session
from src.core.domain.usage_data import UsageData

# Type variable for generic repository interfaces
T = TypeVar("T")


class IRepository(Generic[T], ABC):
    """Generic repository interface for data access operations.

    This interface defines the basic CRUD operations for entities.
    """

    @abstractmethod
    async def get_by_id(self, id: str) -> T | None:
        """Get an entity by its ID.

        Args:
            id: The unique identifier of the entity

        Returns:
            The entity if found, None otherwise
        """

    @abstractmethod
    async def get_all(self) -> list[T]:
        """Get all entities.

        Returns:
            A list of all entities
        """

    @abstractmethod
    async def add(self, entity: T) -> T:
        """Add a new entity.

        Args:
            entity: The entity to add

        Returns:
            The added entity (with any generated fields populated)
        """

    @abstractmethod
    async def update(self, entity: T) -> T:
        """Update an existing entity.

        Args:
            entity: The entity to update

        Returns:
            The updated entity
        """

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """Delete an entity by its ID.

        Args:
            id: The unique identifier of the entity to delete

        Returns:
            True if the entity was deleted, False if it didn't exist
        """


class ISessionRepository(IRepository["Session"], ABC):
    """Repository interface for Session entities.

    This interface extends the generic repository with Session-specific operations.
    """

    @abstractmethod
    async def get_by_user_id(self, user_id: str) -> list[Session]:
        """Get all sessions for a specific user.

        Args:
            user_id: The user identifier

        Returns:
            A list of sessions belonging to the user
        """

    @abstractmethod
    async def cleanup_expired(self, max_age_seconds: int) -> int:
        """Clean up expired sessions.

        Args:
            max_age_seconds: Maximum age of sessions to keep in seconds

        Returns:
            The number of sessions deleted
        """


class IConfigRepository(ABC):
    """Repository interface for configuration data.

    This interface defines operations for accessing and modifying
    configuration data.
    """

    @abstractmethod
    async def get_config(self, key: str) -> dict[str, Any] | None:
        """Get configuration by key.

        Args:
            key: The configuration key

        Returns:
            The configuration data if found, None otherwise
        """

    @abstractmethod
    async def set_config(self, key: str, config: dict[str, Any]) -> None:
        """Set configuration data.

        Args:
            key: The configuration key
            config: The configuration data to store
        """

    @abstractmethod
    async def delete_config(self, key: str) -> bool:
        """Delete configuration by key.

        Args:
            key: The configuration key to delete

        Returns:
            True if the configuration was deleted, False if it didn't exist
        """


class IUsageRepository(IRepository[UsageData], ABC):
    """Repository interface for UsageData entities.

    This interface extends the generic repository with UsageData-specific operations.
    """

    @abstractmethod
    async def get_by_session_id(self, session_id: str) -> list[UsageData]:
        """Get all usage data for a specific session.

        Args:
            session_id: The session identifier

        Returns:
            A list of usage data for the session
        """

    @abstractmethod
    async def get_stats(self, project: str | None = None) -> dict[str, Any]:
        """Get usage statistics, optionally filtered by project.

        Args:
            project: Optional project filter

        Returns:
            Usage statistics dictionary
        """
