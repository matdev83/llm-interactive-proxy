#!/usr/bin/env python3
"""
Memory leak reproduction script for InMemorySessionRepository.

This script demonstrates that the session repository grows unbounded
when cleanup is disabled (which is the default).
"""

import asyncio
import sys
import os
import tracemalloc
import time
from datetime import datetime, timezone

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
src_path = os.path.join(project_root, 'src')
sys.path.insert(0, src_path)

# Direct imports to test the repository
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository

# Simple session mock to avoid complex dependencies
class MockSession:
    def __init__(self, session_id: str, user_id: str = "test_user"):
        self.id = session_id
        self.user_id = user_id
        self.created_at = datetime.now(timezone.utc)
        self.last_active_at = datetime.now(timezone.utc)
        self.history = []

def main():
    """Demonstrate memory leak in InMemorySessionRepository."""
    print("=== Memory Leak Reproduction Script ===")
    print("Testing InMemorySessionRepository for unbounded growth")
    
    # Start memory tracking
    tracemalloc.start()
    
    # Create repository
    repo = InMemorySessionRepository()
    
    # Track initial state
    snapshot1 = tracemalloc.take_snapshot()
    
    print(f"Initial session count: 0")
    
    # Create many sessions (simulating traffic over time)
    session_count = 1000
    print(f"Creating {session_count} sessions...")
    
    for i in range(session_count):
        session = MockSession(f"session_{i}", f"user_{i % 10}")
        asyncio.run(repo.add(session))
        
        if i % 100 == 0:
            print(f"Created {i} sessions...")
    
    # Check final state
    final_sessions = len(asyncio.run(repo.get_all()))
    snapshot2 = tracemalloc.take_snapshot()
    
    print(f"Final session count: {final_sessions}")
    print(f"Sessions added: {final_sessions}")
    
    # Show memory growth
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    print("\nTop memory changes:")
    for stat in top_stats[:5]:
        print(f"  {stat}")
    
    # Check internal dictionaries sizes
    print(f"\nInternal state sizes:")
    print(f"  _sessions: {len(repo._sessions)}")
    print(f"  _user_sessions: {len(repo._user_sessions)}")
    print(f"  _last_accessed: {len(repo._last_accessed)}")
    print(f"  _client_sessions: {len(repo._client_sessions)}")
    print(f"  _fingerprints: {len(repo._fingerprints)}")
    print(f"  _fingerprint_bundles: {len(repo._fingerprint_bundles)}")
    
    # Test cleanup method (but show it's not called automatically)
    print("\nTesting manual cleanup (with max_age=0)...")
    cleaned = asyncio.run(repo.cleanup_expired(max_age_seconds=0))
    print(f"Sessions cleaned with max_age=0: {cleaned}")
    
    remaining_sessions = len(asyncio.run(repo.get_all()))
    print(f"Sessions remaining after cleanup: {remaining_sessions}")
    
    # Show that memory is not freed without cleanup
    if final_sessions > 0 and cleaned == 0:
        print("\n⚠️  MEMORY LEAK CONFIRMED: Sessions are never cleaned up!")
        print("   The repository grows unbounded when cleanup is not enabled.")
        print("   By default, session_cleanup_enabled=False in lifecycle.py")
        return True
    else:
        print("\n✅ No memory leak detected.")
        return False

if __name__ == "__main__":
    leak_confirmed = main()
    sys.exit(1 if leak_confirmed else 0)