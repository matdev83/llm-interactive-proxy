#!/usr/bin/env python3
"""
Accurate reproduction of InMemorySessionRepository memory leak.
Based on the actual code - tests if sessions with last_active_at are properly cleaned.
"""

import asyncio
import gc
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

# Mock actual Session behavior
class MockSession:
    def __init__(self, session_id: str):
        self.id = session_id
        self.history = []
        # This is key - the real Session has last_active_at
        self.last_active_at = None

# Actual InMemorySessionRepository cleanup logic
class InMemorySessionRepository:
    def __init__(self):
        self._sessions = {}
        self._last_accessed = {}
        print("Repository initialized")
    
    def add(self, entity):
        self._sessions[entity.id] = entity
        self._last_accessed[entity.id] = time.time()
    
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
                        session_id, now_timestamp
                    )
                    age = now_timestamp - last_access_timestamp
            else:
                # Fall back to internal tracking
                last_access_timestamp = self._last_accessed.get(
                    session_id, now_timestamp
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


async def test_memory_leak():
    """Test for actual memory leak."""
    print("Testing InMemorySessionRepository for memory leak...")
    
    tracemalloc.start()
    
    repo = InMemorySessionRepository()
    
    # Add sessions WITHOUT last_active_at set (this might be the bug!)
    initial_memory = 0
    for i in range(1000):
        session = MockSession(f"session_{i}")
        # CRITICAL: Don't set last_active_at - this triggers the fallback path
        # session.last_active_at = datetime.now(timezone.utc)  # Comment this out!
        repo.add(session)
        
        if i == 0:
            gc.collect()
            initial_memory, _ = tracemalloc.get_traced_memory()
        
        if i % 200 == 0:
            current_size = len(repo._sessions)
            print(f"Added {i} sessions, current size: {current_size}")
    
    gc.collect()
    
    current, peak = tracemalloc.get_traced_memory()
    memory_growth = current - initial_memory
    
    print(f"\nBefore cleanup:")
    print(f"Sessions in memory: {len(repo._sessions)}")
    print(f"Memory growth: {memory_growth / 1024:.2f} KB")
    
    # Run cleanup with very short TTL
    print("\nRunning cleanup (TTL=2 seconds)...")
    cleaned = await repo.cleanup_expired(max_age_seconds=2)
    print(f"Cleaned {cleaned} sessions")
    
    gc.collect()
    current_after, peak_after = tracemalloc.get_traced_memory()
    
    print(f"\nAfter cleanup:")
    print(f"Sessions remaining: {len(repo._sessions)}")
    print(f"Memory after cleanup: {current_after / 1024:.2f} KB")
    print(f"Memory retained: {(current_after - initial_memory) / 1024:.2f} KB")
    
    # Check for memory leak
    sessions_remaining = len(repo._sessions)
    if sessions_remaining > 900:  # Should have cleaned most
        print(f"MEMORY LEAK: {sessions_remaining} sessions remaining after cleanup!")
        return True
    
    if memory_growth > 200 * 1024:  # More than 200KB growth
        print(f"MEMORY LEAK: Excessive memory growth: {memory_growth / 1024:.2f} KB!")
        return True
    
    print("Cleanup appears to work correctly.")
    return False


if __name__ == "__main__":
    is_leak = asyncio.run(test_memory_leak())
    if is_leak:
        print("\nCONFIRMED: InMemorySessionRepository has a memory leak!")
        print("Sessions without last_active_at are not being cleaned up properly.")
        sys.exit(1)
    else:
        print("\nNo memory leak detected.")
        sys.exit(0)