"""
Demo test to show the automatic enforcement in action.
"""

import pytest
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


def test_safe_session_usage(safe_session_service):
    """This test shows the recommended approach."""
    # No warnings - uses the safe session service
    safe_session_service.set('data', 'test')
    result = safe_session_service.get('data')
    assert result == "test"
