from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.session import Session


class ISessionService(ABC):
    @abstractmethod
    async def get_session(self, session_id: str) -> Session:
        pass

    @abstractmethod
    async def create_session(self, session_id: str) -> Session:
        pass

    @abstractmethod
    async def get_or_create_session(self, session_id: str | None = None) -> Session:
        pass

    @abstractmethod
    async def update_session(self, session: Session) -> None:
        pass

    @abstractmethod
    async def update_session_backend_config(
        self, session_id: str, backend_type: str, model: str
    ) -> None:
        """Update the backend configuration for a given session."""

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        pass

    @abstractmethod
    async def get_all_sessions(self) -> list[Session]:
        pass
