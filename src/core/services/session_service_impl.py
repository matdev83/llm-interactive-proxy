from __future__ import annotations

from src.core.domain.session import Session
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.session_service_interface import ISessionService


class SessionService(ISessionService):
    """Concrete session service implementation."""

    def __init__(self, session_repository: ISessionRepository) -> None:
        self._session_repository = session_repository

    async def get_session(self, session_id: str) -> Session:
        session = await self._session_repository.get_by_id(session_id)
        if not session:
            session = Session(session_id=session_id)
            await self._session_repository.add(session)
        return session
        
    async def get_session_async(self, session_id: str) -> Session:
        """Legacy compatibility method, identical to get_session."""
        return await self.get_session(session_id)

    async def get_or_create_session(self, session_id: str | None = None) -> Session:
        if session_id is None:
            import uuid

            session_id = str(uuid.uuid4())
        return await self.get_session(session_id)

    async def create_session(self, session_id: str) -> Session:
        session = Session(session_id=session_id)
        await self._session_repository.add(session)
        return session

    async def update_session(self, session: Session) -> None:
        await self._session_repository.update(session)

    async def delete_session(self, session_id: str) -> bool:
        return await self._session_repository.delete(session_id)

    async def get_all_sessions(self) -> list[Session]:
        return await self._session_repository.get_all()


