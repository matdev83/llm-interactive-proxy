from __future__ import annotations

from src.core.domain.session import Session
from src.core.interfaces.repositories import ISessionRepository
from src.core.interfaces.session_service import ISessionService


class SessionService(ISessionService):
    """
    A service for managing user sessions.
    """

    def __init__(self, session_repository: ISessionRepository):
        self._session_repository = session_repository

    async def get_session(self, session_id: str) -> Session:
        session = await self._session_repository.get_by_id(session_id)
        if not session:
            # Create a new session if not found
            session = Session(session_id=session_id)
            await self._session_repository.add(session)
        return session

    async def get_or_create_session(self, session_id: str | None = None) -> Session:
        """Get existing session or create a new one.

        If session_id is None, generate a new UUID for the session.
        """
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
