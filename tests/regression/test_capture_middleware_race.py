"""Regression test for MemoryCaptureMiddleware race condition."""

import asyncio
from unittest.mock import Mock

from src.core.memory.capture_middleware import MemoryCaptureMiddleware


class MockMemoryService:
    """Mock memory service for testing."""

    def __init__(self, sleep_time=0.01):
        self.enabled_sessions = {}
        self.enable_count = 0
        self.enable_lock = asyncio.Lock()
        self.sleep_time = sleep_time

    def is_available(self):
        return True

    async def is_enabled_for_session(self, session_id):
        # Simulate realistic async check
        await asyncio.sleep(0.001)
        async with self.enable_lock:
            return session_id in self.enabled_sessions

    async def enable_for_session(self, session_id, user_id=None, **kwargs):
        # Simulate slow async operation to create race window
        await asyncio.sleep(self.sleep_time)
        async with self.enable_lock:
            if session_id not in self.enabled_sessions:
                self.enabled_sessions[session_id] = True
                self.enable_count += 1
                return True
            # Session already enabled (double-enable due to race)
            return False


async def test_concurrent_auto_enable_prevents_duplicates():
    """Test that concurrent auto-enable requests don't cause duplicate enables."""
    config = Mock()
    config.default_enabled = True
    mock_service = MockMemoryService()
    middleware = MemoryCaptureMiddleware(mock_service, config)

    session_id = "test-session"

    async def request_handler():
        request = Mock()
        request.messages = []
        await middleware.capture_request(
            session_id=session_id, request=request, user_id="test-user"
        )

    # Create many concurrent requests for same session
    tasks = [request_handler() for _ in range(20)]
    await asyncio.gather(*tasks)

    # Session should only be enabled once
    assert mock_service.enable_count == 1, (
        f"Expected 1 enable, got {mock_service.enable_count} - "
        "race condition caused duplicate enables!"
    )
    assert session_id in mock_service.enabled_sessions


async def test_different_sessions_can_enable_concurrently():
    """Test that different sessions can be enabled concurrently."""
    config = Mock()
    config.default_enabled = True
    mock_service = MockMemoryService()
    middleware = MemoryCaptureMiddleware(mock_service, config)

    async def request_handler(session_id):
        request = Mock()
        request.messages = []
        await middleware.capture_request(
            session_id=session_id, request=request, user_id="test-user"
        )

    # Create concurrent requests for different sessions
    session_ids = [f"session-{i}" for i in range(10)]
    tasks = [request_handler(sid) for sid in session_ids]
    await asyncio.gather(*tasks)

    # Each session should be enabled once
    assert (
        mock_service.enable_count == 10
    ), f"Expected 10 enables (one per session), got {mock_service.enable_count}"

    for session_id in session_ids:
        assert (
            session_id in mock_service.enabled_sessions
        ), f"Session {session_id} was not enabled"


async def test_ttlcache_respects_max_size():
    """Test that TTLCache prevents unbounded growth."""
    config = Mock()
    config.default_enabled = True
    mock_service = MockMemoryService(sleep_time=0)
    middleware = MemoryCaptureMiddleware(mock_service, config)

    # Enable more sessions than TTLCache maxsize (10000)
    async def enable_session(i):
        request = Mock()
        request.messages = []
        await middleware.capture_request(
            session_id=f"session-{i}",
            request=request,
            user_id=f"user-{i % 100}",  # 100 users
        )

    # Try to enable 10100 sessions (more than maxsize, reduced from 12000 for performance)
    # Still exceeds maxsize of 10000 to test eviction behavior
    tasks = [enable_session(i) for i in range(10100)]
    await asyncio.gather(*tasks)

    # Cache should not grow unbounded (cachetools TTLCache handles this)
    cache_size = len(middleware._auto_enabled_sessions)
    assert (
        cache_size <= 10000
    ), f"TTLCache grew to {cache_size}, exceeding maxsize of 10000"


async def test_already_enabled_session_not_re_enabled():
    """Test that already-enabled sessions are not re-enabled."""
    config = Mock()
    config.default_enabled = True
    mock_service = MockMemoryService()

    # Pre-enable a session
    async with mock_service.enable_lock:
        mock_service.enabled_sessions["pre-enabled"] = True
        mock_service.enable_count = 1

    middleware = MemoryCaptureMiddleware(mock_service, config)

    request = Mock()
    request.messages = []
    await middleware.capture_request(
        session_id="pre-enabled", request=request, user_id="test-user"
    )

    # Should not re-enable already-enabled session
    assert mock_service.enable_count == 1, "Already-enabled session was re-enabled!"


async def test_no_auto_enable_when_default_disabled():
    """Test that auto-enable doesn't happen when default_enabled is False."""
    config = Mock()
    config.default_enabled = False
    mock_service = MockMemoryService()
    middleware = MemoryCaptureMiddleware(mock_service, config)

    async def request_handler():
        request = Mock()
        request.messages = []
        await middleware.capture_request(
            session_id=f"session-{asyncio.current_task().get_name()}",
            request=request,
            user_id="test-user",
        )

    tasks = [request_handler() for _ in range(10)]
    await asyncio.gather(*tasks)

    # No sessions should be auto-enabled
    assert (
        mock_service.enable_count == 0
    ), f"Expected 0 enables with default_enabled=False, got {mock_service.enable_count}"


if __name__ == "__main__":
    asyncio.run(test_concurrent_auto_enable_prevents_duplicates())
    asyncio.run(test_different_sessions_can_enable_concurrently())
    asyncio.run(test_ttlcache_respects_max_size())
    asyncio.run(test_already_enabled_session_not_re_enabled())
    asyncio.run(test_no_auto_enable_when_default_disabled())
    print("All tests passed!")
