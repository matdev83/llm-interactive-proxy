"""
Tests for session manager functionality using proper DI approach.

This file contains tests for session management functionality,
refactored to use proper dependency injection instead of direct app.state access.
"""

import pytest
from fastapi import FastAPI
from src.core.app.test_builder import build_minimal_test_app
from src.core.domain.session import SessionInteraction
from src.core.interfaces.session_service_interface import ISessionService

from tests.utils.test_di_utils import get_required_service_from_app


@pytest.fixture
def app() -> FastAPI:
    """Create a minimal test app for testing."""
    return build_minimal_test_app()


@pytest.fixture
def session_service(app: FastAPI) -> ISessionService:
    """Create a session service for testing using proper DI."""
    return get_required_service_from_app(app, ISessionService)


def test_session_service_can_create_sessions(app: FastAPI) -> None:
    """Test that session service can create and manage sessions."""
    service = get_required_service_from_app(app, ISessionService)

    # This is a basic test to verify the service works
    assert service is not None


@pytest.mark.asyncio
async def test_session_creation_and_retrieval(session_service: ISessionService) -> None:
    """Test that sessions can be created and retrieved."""
    session = await session_service.get_or_create_session("test-session")
    assert session.session_id == "test-session"

    # Retrieve the same session
    retrieved_session = await session_service.get_session("test-session")
    assert retrieved_session.session_id == "test-session"


@pytest.mark.asyncio
async def test_session_update_and_persistence(session_service: ISessionService) -> None:
    """Test that session updates are persisted."""
    session = await session_service.get_or_create_session("update-test")

    # Add some history to the session
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


# Suppress Windows ProactorEventLoop warnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
