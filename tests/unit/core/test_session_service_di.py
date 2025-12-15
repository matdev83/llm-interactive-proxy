import pytest
from src.core.app.test_builder import build_minimal_test_app
from src.core.domain.session import SessionInteraction
from src.core.interfaces.session_service_interface import ISessionService

from tests.utils.test_di_utils import get_required_service_from_app


@pytest.mark.asyncio
async def test_session_creation():
    """Test creating a new session using proper DI."""
    # Arrange
    app = build_minimal_test_app()
    service = get_required_service_from_app(app, ISessionService)
    session_id = "test-session-id"

    # Act
    session = await service.get_session(session_id)

    # Assert
    assert session is not None
    assert session.session_id == session_id
    assert len(session.history) == 0


@pytest.mark.asyncio
async def test_session_retrieval():
    """Test retrieving an existing session using proper DI."""
    # Arrange
    app = build_minimal_test_app()
    service = get_required_service_from_app(app, ISessionService)
    session_id = "test-session-id"

    # Create a session first
    session1 = await service.get_session(session_id)

    # Act - Retrieve the same session
    session2 = await service.get_session(session_id)

    # Assert
    assert session2 is not None
    assert session2.session_id == session_id
    assert session1.id == session2.id  # Same session


@pytest.mark.asyncio
async def test_session_update():
    """Test updating a session using proper DI."""
    # Arrange
    app = build_minimal_test_app()
    service = get_required_service_from_app(app, ISessionService)
    session_id = "test-session-id"

    # Create a session
    session = await service.get_session(session_id)

    # Add an interaction
    interaction = SessionInteraction(
        prompt="Hello", handler="backend", response="Hi there!"
    )
    session.add_interaction(interaction)  # type: ignore[arg-type]  # (we know it's a Session)

    # Act
    await service.update_session(session)

    # Retrieve and verify
    updated_session = await service.get_session(session_id)

    # Assert
    assert len(updated_session.history) == 1
    assert updated_session.history[0].prompt == "Hello"
    assert updated_session.history[0].response == "Hi there!"


@pytest.mark.asyncio
async def test_session_deletion():
    """Test deleting a session using proper DI."""
    # Arrange
    app = build_minimal_test_app()
    service = get_required_service_from_app(app, ISessionService)
    session_id = "test-session-id"

    # Create a session
    await service.get_session(session_id)

    # Act
    result = await service.delete_session(session_id)

    # Assert
    assert result is True

    # Try to get the deleted session - should create a new one
    new_session = await service.get_session(session_id)
    assert new_session is not None
    assert new_session.session_id == session_id
    assert len(new_session.history) == 0  # Fresh session


@pytest.mark.asyncio
async def test_get_all_sessions():
    """Test getting all sessions using proper DI."""
    # Arrange
    app = build_minimal_test_app()
    service = get_required_service_from_app(app, ISessionService)

    # Create multiple sessions
    await service.get_session("session1")
    await service.get_session("session2")
    await service.get_session("session3")

    # Act
    all_sessions = await service.get_all_sessions()

    # Assert
    assert len(all_sessions) == 3
    session_ids = {s.session_id for s in all_sessions}
    assert session_ids == {"session1", "session2", "session3"}
