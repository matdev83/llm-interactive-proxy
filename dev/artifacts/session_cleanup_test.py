#!/usr/bin/env python3
"""
Test script to verify InMemorySessionRepository memory management.
Tests whether sessions are properly cleaned up or if they accumulate.
"""

import asyncio
import gc
import sys
import time
import tracemalloc
from pathlib import Path

# Mock the required classes for testing
class MockSession:
    def __init__(self, session_id: str):
        self.id = session_id
        self.history = []
        self.last_active_at = None

class MockInMemorySessionRepository:
    """Simplified version to test memory management."""
    
    def __init__(self):
        self._sessions = {}
        self._user_sessions = {}
        self._last_accessed = {}
        print("Repository initialized")
    
    def add(self, session):
        """Add a session."""
        self._sessions[session.id] = session
        self._last_accessed[session.id] = time.time()
        
        if hasattr(session, "user_id") and session.user_id:
            if session.user_id not in self._user_sessions:
                self._user_sessions[session.user_id] = []
            self._user_sessions[session.user_id].append(session.id)
    
    async def cleanup_expired(self, max_age_seconds: int):
        """Simplified cleanup."""
        now = time.time()
        expired_ids = []
        
        for session_id, last_accessed in self._last_accessed.items():
            if now - last_accessed > max_age_seconds:
                expired_ids.append(session_id)
        
        for session_id in expired_ids:
            if session_id in self._sessions:
                del self._sessions[session_id]
            if session_id in self._last_accessed:
                del self._last_accessed[session_id]
        
        return len(expired_ids)


async def test_session_cleanup():
    """Test if sessions are properly cleaned up."""
    print("Testing InMemorySessionRepository memory management...")
    
    tracemalloc.start()
    
    repo = MockInMemorySessionRepository()
    
    # Add many sessions
    initial_memory = 0
    for i in range(1000):
        session = MockSession(f"session_{i}")
        session.user_id = f"user_{i % 100}"  # 100 different users
        repo.add(session)
        
        if i == 0:
            gc.collect()
            initial_memory, _ = tracemalloc.get_traced_memory()
        
        if i % 200 == 0:
            current_size = len(repo._sessions)
            print(f"Added {i} sessions, current size: {current_size}")
    
    # Don't run cleanup - see if memory stays high
    gc.collect()
    
    current, peak = tracemalloc.get_traced_memory()
    memory_growth = current - initial_memory
    
    print(f"\nBefore cleanup:")
    print(f"Sessions in memory: {len(repo._sessions)}")
    print(f"Memory growth: {memory_growth / 1024:.2f} KB")
    
    # Now run cleanup
    print("\nRunning cleanup...")
    cleaned = await repo.cleanup_expired(max_age_seconds=1)  # Very short TTL
    print(f"Cleaned {cleaned} sessions")
    
    gc.collect()
    current_after, peak_after = tracemalloc.get_traced_memory()
    
    print(f"\nAfter cleanup:")
    print(f"Sessions remaining: {len(repo._sessions)}")
    print(f"Memory after cleanup: {current_after / 1024:.2f} KB")
    print(f"Memory retained: {(current_after - initial_memory) / 1024:.2f} KB")
    
    # Memory leak detection
    if len(repo._sessions) > 100:  # Should have cleaned most
        print("MEMORY LEAK: Sessions not properly cleaned up!")
        return True
    
    if memory_growth > 500 * 1024:  # More than 500KB growth is suspicious
        print("MEMORY LEAK: Excessive memory growth!")
        return True
    
    print("Session cleanup appears to work correctly.")
    return False


if __name__ == "__main__":
    is_leak = asyncio.run(test_session_cleanup())
    if is_leak:
        print("\nMEMORY LEAK DETECTED!")
        sys.exit(1)
    else:
        print("\nNo memory leak detected.")
        sys.exit(0)