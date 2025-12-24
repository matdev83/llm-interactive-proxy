"""Regression test for MemoryCaptureMiddleware race condition in auto-enable logic."""

import asyncio

import pytest
from src.core.memory.capture_middleware import MemoryCaptureMiddleware
from tests.mocks.memory_service_mock import MemoryServiceMock


@pytest.mark.asyncio
async def test_capture_request_auto_enable_no_race_condition() -> None:
    """Test that concurrent capture_request calls don't cause race in auto-enable logic.

    This tests the fix for the check-then-act pattern race condition where
    multiple concurrent requests for the same session could all pass the
    'session_id not in self._auto_enabled_sessions' check and call
    enable_for_session() multiple times.
    """

    memory_service = MemoryServiceMock()

    class MockConfig:
        default_enabled = True

    config = MockConfig()

    middleware = MemoryCaptureMiddleware(memory_service, config)

    session_id = "test-session-123"
    user_id = "test-user"

    # Create multiple concurrent requests for the same session
    num_concurrent = 10

    async def make_request(i: int) -> None:
        from src.core.domain.chat import ChatMessage, ChatRequest

        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="user", content=f"Test message {i}"),
            ],
        )
        await middleware.capture_request(
            session_id, request, user_id=user_id, client_id="client-1"
        )

    # Run all requests concurrently
    await asyncio.gather(*[make_request(i) for i in range(num_concurrent)])

    # Verify that enable_for_session was called exactly ONCE, despite concurrent requests
    enable_count = memory_service.get_enable_call_count(session_id)
    assert (
        enable_count == 1
    ), f"Expected enable_for_session to be called exactly once, but was called {enable_count} times"

    # Verify that the session was actually enabled
    is_enabled = await memory_service.is_enabled_for_session(session_id)
    assert is_enabled, "Session should be enabled"

    # Verify that the session is tracked in auto-enabled sessions
    assert session_id in middleware._auto_enabled_sessions, "Session should be in auto-enabled cache"
