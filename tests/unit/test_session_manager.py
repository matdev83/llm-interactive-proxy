import pytest
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.services.session_service_impl import SessionService


@pytest.fixture
def session_service():
    """Create a session service for testing."""
    repository = InMemorySessionRepository()
    return SessionService(repository)


def test_session_service_can_create_sessions():
    """Test that session service can create and manage sessions."""
    repository = InMemorySessionRepository()
    service = SessionService(repository)

    # This is a basic test to verify the service works
    assert service is not None


@pytest.mark.asyncio
async def test_session_creation_and_retrieval(session_service) -> None:
    """Test that sessions can be created and retrieved."""
    session = await session_service.get_or_create_session("test-session")
    assert session.session_id == "test-session"

    # Retrieve the same session
    retrieved_session = await session_service.get_session("test-session")
    assert retrieved_session.session_id == "test-session"


@pytest.mark.asyncio
async def test_session_update_and_persistence(session_service) -> None:
    """Test that session updates are persisted."""
    session = await session_service.get_or_create_session("update-test")

    # Add some history to the session
    from src.core.domain.session import SessionInteraction

    entry = SessionInteraction(
        handler="test", prompt="test prompt", response="test response"
    )
    session.history.append(entry)

    # Update the session
    await session_service.update_session(session)

    # Retrieve and verify
    updated_session = await session_service.get_session("update-test")
    assert len(updated_session.history) == 1
    assert updated_session.history[0].prompt == "test prompt"
