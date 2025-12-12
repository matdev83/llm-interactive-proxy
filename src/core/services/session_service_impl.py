from __future__ import annotations

import logging

from src.core.domain.session import Session
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.session_sanitizer import (
    SessionSanitizer,
    get_default_session_sanitizer,
)

logger = logging.getLogger(__name__)


class SessionService(ISessionService):
    """Concrete session service implementation."""

    def __init__(
        self,
        session_repository: ISessionRepository,
        session_sanitizer: SessionSanitizer | None = None,
    ) -> None:
        self._session_repository = session_repository
        self._session_sanitizer = session_sanitizer or get_default_session_sanitizer()

    async def get_session(self, session_id: str) -> Session:
        session = await self._session_repository.get_by_id(session_id)
        if not session:
            session = Session(session_id=session_id)
            await self._session_repository.add(session)
        return session

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

    async def update_session_backend_config(
        self, session_id: str, backend_type: str, model: str
    ) -> None:
        session = await self.get_session(session_id)
        # SessionState is immutable, so with_backend_config returns a new instance
        current_config = session.state.backend_config
        previous_backend = getattr(current_config, "backend_type", None)

        # Clear thought signature cache if switching between incompatible backends
        if self._session_sanitizer.should_sanitize(previous_backend, backend_type):
            cleared_count = self._session_sanitizer.clear_signature_cache(session_id)
            if cleared_count > 0:
                logger.info(
                    "Cleared %d thought signatures for session %s on backend switch: %s -> %s",
                    cleared_count,
                    session_id[:8] if session_id else "none",
                    previous_backend or "none",
                    backend_type or "none",
                )

        updated_config = current_config.with_backend(backend_type).with_model(model)
        new_state = session.state.with_backend_config(updated_config)
        session.state = new_state
        await self._session_repository.update(session)

    async def delete_session(self, session_id: str) -> bool:
        return await self._session_repository.delete(session_id)

    async def get_all_sessions(self) -> list[Session]:
        return await self._session_repository.get_all()
