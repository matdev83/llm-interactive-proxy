from __future__ import annotations

from src.core.commands.session_state_adapter import SessionStateAdapter
from src.core.domain.session import Session
from src.core.interfaces.command_state_service_interface import ICommandStateService
from src.core.interfaces.session_service_interface import ISessionService


class CommandStateService(ICommandStateService):
    """Adapter around the session service tailored for command execution."""

    def __init__(self, session_service: ISessionService) -> None:
        self._session_service = session_service

    async def get_session(self, session_id: str) -> Session | None:
        return await self._session_service.get_session(session_id)

    async def update_session(self, session: Session) -> None:
        await self._session_service.update_session(session)

    def build_session_adapter(self, session: Session) -> SessionStateAdapter:
        return SessionStateAdapter(session)
