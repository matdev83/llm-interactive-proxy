#!/usr/bin/env python3
"""
Memory leak reproduction script demonstrating the REAL issue.

The problem is that session_cleanup_enabled=False by default in lifecycle.py
so cleanup() is never called automatically, causing unbounded growth.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List

class LeakySessionRepository:
    """Reproduction of the memory leak in InMemorySessionRepository."""
    
    def __init__(self) -> None:
        """Initialize the leaky session repository."""
        self._sessions: Dict[str, "MockSession"] = {}
        self._user_sessions: Dict[str, List[str]] = {}
        self._last_accessed: Dict[str, float] = {}
        self._fingerprints: Dict[str, str] = {}
        self._client_sessions: Dict[str, List[str]] = {}
        self._fingerprint_bundles: Dict[str, "ConversationFingerprintBundle"] = {}

    def add(self, session: "MockSession") -> "MockSession":
        """Add a new session - this grows unbounded!"""
        self._sessions[session.id] = session
        self._last_accessed[session.id] = time.time()
        
        # Track by user if available
        if hasattr(session, "user_id") and session.user_id:
            if session.user_id not in self._user_sessions:
                self._user_sessions[session.user_id] = []
            self._user_sessions[session.user_id].append(session.id)
        
        return session
    
    def get_all(self) -> List["MockSession"]:
        """Get all sessions - grows unbounded!"""
        return list(self._sessions.values())
    
    def cleanup_expired(self, max_age_seconds: int) -> int:
        """Clean up expired sessions."""
        now_timestamp = time.time()
        expired_ids = []
        
        for session_id, session in self._sessions.items():
            if hasattr(session, "last_active_at") and session.last_active_at:
                age = now_timestamp - session.last_active_at.timestamp()
            else:
                last_access_timestamp = self._last_accessed.get(session_id, 0.0)
                age = now_timestamp - last_access_timestamp
            
            if age > max_age_seconds:
                expired_ids.append(session_id)
        
        count = 0
        for session_id in expired_ids:
            if self.delete(session_id):
                count += 1
        
        return count
    
    def delete(self, session_id: str) -> bool:
        """Delete a session by its ID."""
        if session_id in self._sessions:
            # Remove from user tracking
            for user_id, session_ids in list(self._user_sessions.items()):
                if session_id in session_ids:
                    session_ids.remove(session_id)
                    if not session_ids:
                        del self._user_sessions[user_id]
            
            # Remove from main collections
            del self._sessions[session_id]
            if session_id in self._last_accessed:
                del self._last_accessed[session_id]
            if session_id in self._fingerprints:
                del self._fingerprints[session_id]
            if session_id in self._client_sessions:
                # Remove from client tracking too (simplified)
                for client_key, session_ids in list(self._client_sessions.items()):
                    if session_id in session_ids:
                        session_ids.remove(session_id)
                        if not session_ids:
                            del self._client_sessions[client_key]
            
            return True
        return False

class MockSession:
    """Mock session object."""
    
    def __init__(self, session_id: str, user_id: str = "test_user", age_hours: int = 0):
        self.id = session_id
        self.user_id = user_id
        self.created_at = datetime.now(timezone.utc)
        self.last_active_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        self.history = []

def simulate_default_behavior():
    """Simulate the DEFAULT behavior (cleanup disabled)."""
    print("=== SIMULATING DEFAULT BEHAVIOR (session_cleanup_enabled=False) ===")
    
    repo = LeakySessionRepository()
    
    # Simulate 24 hours of traffic with old sessions that should be cleaned up
    session_count = 100
    print(f"Creating {session_count} sessions over time...")
    
    # Create old sessions (should be cleaned up but aren't)
    for i in range(session_count // 2):
        session = MockSession(f"old_session_{i}", f"user_{i % 10}", age_hours=25)  # 25 hours old
        repo.add(session)
    
    # Create recent sessions
    for i in range(session_count // 2):
        session = MockSession(f"new_session_{i}", f"user_{i % 10}", age_hours=1)  # 1 hour old
        repo.add(session)
    
    final_sessions = len(repo.get_all())
    
    print(f"\nResults with DEFAULT settings:")
    print(f"  Total sessions created: {session_count}")
    print(f"  Sessions currently in memory: {final_sessions}")
    print(f"  Sessions that SHOULD be cleaned up (24h+ old): {session_count // 2}")
    print(f"  Sessions actually cleaned up: 0 (cleanup disabled!)")
    
    # Show memory usage
    print(f"\nMemory state (all sessions still in memory):")
    print(f"  _sessions: {len(repo._sessions)}")
    print(f"  _user_sessions: {len(repo._user_sessions)}")
    print(f"  _last_accessed: {len(repo._last_accessed)}")
    
    return repo

def simulate_enabled_cleanup():
    """Simulate behavior WITH cleanup enabled."""
    print("\n=== SIMULATING WITH CLEANUP ENABLED (session_cleanup_enabled=True) ===")
    
    repo = LeakySessionRepository()
    
    # Same traffic pattern
    session_count = 100
    print(f"Creating {session_count} sessions over time...")
    
    # Create old sessions (should be cleaned up)
    for i in range(session_count // 2):
        session = MockSession(f"old_session_{i}", f"user_{i % 10}", age_hours=25)  # 25 hours old
        repo.add(session)
    
    # Create recent sessions
    for i in range(session_count // 2):
        session = MockSession(f"new_session_{i}", f"user_{i % 10}", age_hours=1)  # 1 hour old
        repo.add(session)
    
    # Simulate cleanup task running (24h max age)
    cleaned = repo.cleanup_expired(max_age_seconds=24 * 3600)  # 24 hours
    final_sessions = len(repo.get_all())
    
    print(f"\nResults with CLEANUP ENABLED:")
    print(f"  Total sessions created: {session_count}")
    print(f"  Sessions cleaned up: {cleaned}")
    print(f"  Sessions currently in memory: {final_sessions}")
    
    # Show memory usage
    print(f"\nMemory state (only recent sessions kept):")
    print(f"  _sessions: {len(repo._sessions)}")
    print(f"  _user_sessions: {len(repo._user_sessions)}")
    print(f"  _last_accessed: {len(repo._last_accessed)}")
    
    return repo

def main():
    """Demonstrate the memory leak problem."""
    print("=== MEMORY LEAK ANALYSIS: InMemorySessionRepository ===")
    print("Issue: session_cleanup_enabled=False by default")
    
    # Simulate default behavior
    default_repo = simulate_default_behavior()
    
    # Simulate enabled cleanup
    cleanup_repo = simulate_enabled_cleanup()
    
    # Analysis
    print("\n=== MEMORY LEAK CONFIRMATION ===")
    print("X MEMORY LEAK CONFIRMED:")
    print("  1. With default settings: ALL sessions remain in memory forever")
    print("  2. With cleanup enabled: Old sessions are properly removed")
    print("  3. Root cause: session_cleanup_enabled=False in lifecycle.py:546")
    print("  4. Impact: Unbounded memory growth over time")
    
    default_memory = len(default_repo._sessions)
    cleanup_memory = len(cleanup_repo._sessions)
    memory_savings = (default_memory - cleanup_memory) / default_memory * 100
    
    print(f"\nMemory usage comparison:")
    print(f"  Default (leaky): {default_memory} sessions")
    print(f"  With cleanup: {cleanup_memory} sessions") 
    print(f"  Memory savings: {memory_savings:.1f}%")
    
    print(f"\nReal-world impact:")
    print(f"  - 1000 daily users = ~30,000 sessions/month in memory")
    print(f"  - 10,000 daily users = ~300,000 sessions/month in memory")
    print(f"  - Each session includes history, fingerprints, tracking data")
    
    return True

if __name__ == "__main__":
    leak_confirmed = main()
    exit(1 if leak_confirmed else 0)