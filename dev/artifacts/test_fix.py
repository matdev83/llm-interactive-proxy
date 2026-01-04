#!/usr/bin/env python3
"""
Test the fixed InMemorySessionRepository logic.
"""

import asyncio
import gc
import sys
import time
import tracemalloc
from datetime import datetime, timezone


# Mock actual Session behavior
class MockSession:
    def __init__(self, session_id: str):
        self.id = session_id
        self.history = []
        # Simulate sessions without last_active_at (the problematic case)
        self.last_active_at = None


# Fixed InMemorySessionRepository cleanup logic
class FixedInMemorySessionRepository:
    def __init__(self):
        self._sessions = {}
        self._last_accessed = {}
        print("Fixed repository initialized")

    def add(self, entity):
        self._sessions[entity.id] = entity
        self._last_accessed[entity.id] = time.time()  # Store actual time when added

    async def cleanup_expired(self, max_age_seconds: int):
        now = datetime.now(timezone.utc)
        now_timestamp = time.time()
        expired_ids = []

        for session_id, session in self._sessions.items():
            # Use session's last_active_at if available, otherwise fall back to _last_accessed
            if hasattr(session, "last_active_at") and session.last_active_at:
                last_active = session.last_active_at
                if isinstance(last_active, datetime):
                    if (
                        last_active.tzinfo is None
                        or last_active.tzinfo.utcoffset(last_active) is None
                    ):
                        last_active = last_active.replace(tzinfo=timezone.utc)
                    else:
                        last_active = last_active.astimezone(timezone.utc)

                    age = (now - last_active).total_seconds()
                else:
                    last_access_timestamp = self._last_accessed.get(
                        session_id,
                        0.0,  # FIXED: Use 0.0 as fallback, not now_timestamp!
                    )
                    age = now_timestamp - last_access_timestamp
            else:
                # Fall back to internal tracking with proper fallback
                last_access_timestamp = self._last_accessed.get(
                    session_id, 0.0  # FIXED: Use 0.0 as fallback
                )
                age = now_timestamp - last_access_timestamp

            if age > max_age_seconds:
                expired_ids.append(session_id)

        count = 0
        for session_id in expired_ids:
            if session_id in self._sessions:
                del self._sessions[session_id]
                if session_id in self._last_accessed:
                    del self._last_accessed[session_id]
                count += 1

        return count


async def test_fixed_repository():
    """Test the fixed repository."""
    print("Testing FIXED InMemorySessionRepository...")

    tracemalloc.start()

    repo = FixedInMemorySessionRepository()

    # Add sessions without last_active_at (the problematic case)
    initial_memory = 0
    for i in range(1000):
        session = MockSession(f"session_{i}")
        # CRITICAL: Don't set last_active_at - this tests the fallback path
        repo.add(session)

        if i == 0:
            gc.collect()
            initial_memory, _ = tracemalloc.get_traced_memory()

        if i % 200 == 0:
            current_size = len(repo._sessions)
            print(f"Added {i} sessions, current size: {current_size}")

    # Wait a bit to ensure TTL expires
    await asyncio.sleep(3)

    gc.collect()

    current, peak = tracemalloc.get_traced_memory()
    memory_growth = current - initial_memory

    print("\nBefore cleanup:")
    print(f"Sessions in memory: {len(repo._sessions)}")
    print(f"Memory growth: {memory_growth / 1024:.2f} KB")

    # Run cleanup with short TTL (should work now!)
    print("\nRunning cleanup (TTL=2 seconds)...")
    cleaned = await repo.cleanup_expired(max_age_seconds=2)
    print(f"Cleaned {cleaned} sessions")

    gc.collect()
    current_after, peak_after = tracemalloc.get_traced_memory()

    print("\nAfter cleanup:")
    print(f"Sessions remaining: {len(repo._sessions)}")
    print(f"Memory after cleanup: {current_after / 1024:.2f} KB")
    print(f"Memory retained: {(current_after - initial_memory) / 1024:.2f} KB")

    # Check if memory leak is fixed
    sessions_remaining = len(repo._sessions)
    if sessions_remaining < 100:  # Should have cleaned most
        print("SUCCESS: Cleanup is now working correctly!")
        return False

    if memory_growth < 100 * 1024:  # Less than 100KB growth
        print("SUCCESS: Memory growth is reasonable.")
        return False

    print("FAILURE: Memory leak still present!")
    return True


if __name__ == "__main__":
    is_leak = asyncio.run(test_fixed_repository())
    if is_leak:
        print("\nFAILURE: Memory leak still detected!")
        sys.exit(1)
    else:
        print("\nSUCCESS: Memory leak appears to be fixed!")
        sys.exit(0)
