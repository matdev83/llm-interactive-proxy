"""Repro script for MemoryCaptureMiddleware race condition."""

import asyncio
from unittest.mock import Mock

from src.core.memory.capture_middleware import MemoryCaptureMiddleware


class MockMemoryService:
    """Mock memory service that simulates slow enable operations."""

    def __init__(self):
        self.enabled_sessions = {}

    def is_available(self):
        return True

    async def is_enabled_for_session(self, session_id):
        # Simulate slow check
        await asyncio.sleep(0.01)
        return session_id in self.enabled_sessions

    async def enable_for_session(self, session_id, **kwargs):
        # Simulate slow enable (allowing race window)
        await asyncio.sleep(0.05)
        self.enabled_sessions[session_id] = True
        print(f"Enabled session {session_id}")
        return True


async def test_duplicate_enable_race():
    """Test that concurrent requests for same session cause duplicate enables."""
    config = Mock()
    config.default_enabled = True
    middleware = MemoryCaptureMiddleware(MockMemoryService(), config)

    session_id = "test-session"

    async def request_handler():
        request = Mock()
        request.messages = []
        await middleware.capture_request(
            session_id=session_id,
            request=request,
            user_id="test-user"
        )

    # Simulate 10 concurrent requests for same session
    tasks = [request_handler() for _ in range(10)]
    await asyncio.gather(*tasks)

    # Check if session was enabled multiple times (race condition)
    # In correct behavior, should only be enabled once
    enabled_count = sum(1 for _ in range(10))  # Check logs

    print(f"\nSession {session_id} was processed by {len(tasks)} concurrent requests")
    print("Check logs above - if you see multiple 'Enabled session' messages, race exists!")

    return 0


async def main():
    print("=" * 60)
    print("Testing MemoryCaptureMiddleware race condition...")
    print("=" * 60)
    return await test_duplicate_enable_race()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
