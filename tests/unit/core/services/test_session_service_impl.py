import pytest
from src.core.domain.session import Session
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprintBundle,
)
from src.core.services.session_service_impl import SessionService


class InMemorySessionRepository(ISessionRepository):
    """Simple in-memory session repository for testing."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def get_by_id(self, id: str) -> Session | None:
        return self._sessions.get(id)

    async def get_all(self) -> list[Session]:
        return list(self._sessions.values())

    async def add(self, entity: Session) -> Session:
        self._sessions[entity.session_id] = entity
        return entity

    async def update(self, entity: Session) -> Session:
        self._sessions[entity.session_id] = entity
        return entity

    async def delete(self, id: str) -> bool:
        return self._sessions.pop(id, None) is not None

    async def get_by_user_id(self, user_id: str) -> list[Session]:
        return [
            s for s in self._sessions.values() if getattr(s, "user_id", None) == user_id
        ]

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        return 0

    async def update_fingerprint(self, session_id: str, fingerprint: str) -> None:
        pass

    async def update_client_session(self, session_id: str, client_key: str) -> None:
        pass

    async def find_by_client_and_fingerprint(
        self, client_key: str, fingerprint: str
    ) -> Session | None:
        return None

    async def find_recent_sessions_by_client(
        self, client_key: str, max_age_seconds: int
    ) -> list[Session]:
        return []

    async def get_session_fingerprint(self, session_id: str) -> str | None:
        return None

    async def update_fingerprint_bundle(
        self, session_id: str, bundle: ConversationFingerprintBundle
    ) -> None:
        pass

    async def get_fingerprint_bundle(
        self, session_id: str
    ) -> ConversationFingerprintBundle | None:
        return None

    async def get_session_last_access(self, session_id: str) -> float | None:
        return None


@pytest.mark.asyncio
async def test_update_session_backend_config_updates_backend_and_model() -> None:
    repo = InMemorySessionRepository()
    service = SessionService(repo)

    session = Session(session_id="sess-1")
    await repo.add(session)

    await service.update_session_backend_config("sess-1", "openai", "gpt-4")

    stored = await repo.get_by_id("sess-1")
    assert stored is not None
    assert stored.state.backend_config.backend_type == "openai"
    assert stored.state.backend_config.model == "gpt-4"
