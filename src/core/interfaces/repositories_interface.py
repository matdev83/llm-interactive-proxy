from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from src.core.domain.session import Session
from src.core.domain.usage_data import UsageData

T = TypeVar("T")


class IRepository(Generic[T], ABC):
    @abstractmethod
    async def get_by_id(self, id: str) -> T | None:
        pass

    @abstractmethod
    async def get_all(self) -> list[T]:
        pass

    @abstractmethod
    async def add(self, entity: T) -> T:
        pass

    @abstractmethod
    async def update(self, entity: T) -> T:
        pass

    @abstractmethod
    async def delete(self, id: str) -> bool:
        pass


class ISessionRepository(IRepository["Session"], ABC):
    @abstractmethod
    async def get_by_user_id(self, user_id: str) -> list[Session]:
        pass

    @abstractmethod
    async def cleanup_expired(self, max_age_seconds: int) -> int:
        pass

    @abstractmethod
    async def update_fingerprint(self, session_id: str, fingerprint: str) -> None:
        """Update the conversation fingerprint for a session."""

    @abstractmethod
    async def update_client_session(self, session_id: str, client_key: str) -> None:
        """Track a session as belonging to a specific client."""

    @abstractmethod
    async def find_by_client_and_fingerprint(
        self, client_key: str, fingerprint: str
    ) -> Session | None:
        """Find a session by client key and conversation fingerprint."""

    @abstractmethod
    async def find_recent_sessions_by_client(
        self, client_key: str, max_age_seconds: int
    ) -> list[Session]:
        """Find recent sessions for a client."""

    @abstractmethod
    async def get_session_fingerprint(self, session_id: str) -> str | None:
        """Get the fingerprint for a session."""


class IConfigRepository(ABC):
    @abstractmethod
    async def get_config(self, key: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    async def set_config(self, key: str, config: dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def delete_config(self, key: str) -> bool:
        pass


class IUsageRepository(IRepository[UsageData], ABC):
    @abstractmethod
    async def get_by_session_id(self, session_id: str) -> list[UsageData]:
        pass

    @abstractmethod
    async def get_stats(self, project: str | None = None) -> dict[str, Any]:
        pass
