"""
Demo test to show the automatic enforcement in action.
"""

from unittest.mock import AsyncMock

from src.core.domain.session import Session


def test_problematic_session_mock():
    """This test will trigger warnings due to using AsyncMock for Session."""
    # This should trigger a warning from our SafeAsyncMock
    session_mock = AsyncMock(spec=Session)
    session_mock.session_id = "test-123"
    
    # Use the mock
    result = session_mock.session_id
    assert result == "test-123"


def test_safe_session_usage():
    """This test shows the recommended approach using direct session creation."""
    # Create a test session directly without complex fixtures
    from src.core.domain.session import Session

    session = Session(session_id="test-session")

    # Verify the session was created properly
    assert session is not None
    assert session.session_id == "test-session"
    assert session.state is not None
