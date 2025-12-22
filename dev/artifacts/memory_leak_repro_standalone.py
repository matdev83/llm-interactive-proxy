#!/usr/bin/env python3
"""
Memory leak reproduction script demonstrating the issue.

This standalone version recreates the relevant parts of InMemorySessionRepository
to demonstrate the memory leak without import dependencies.
"""

import time
from datetime import datetime, timezone
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
            del self._sessions[session_id]
            if session_id in self._last_accessed:
                del self._last_accessed[session_id]
            return True
        return False

class MockSession:
    """Mock session object."""
    
    def __init__(self, session_id: str, user_id: str = "test_user"):
        self.id = session_id
        self.user_id = user_id
        self.created_at = datetime.now(timezone.utc)
        self.last_active_at = datetime.now(timezone.utc)
        self.history = []

def main():
    """Demonstrate memory leak."""
    print("=== Memory Leak Reproduction ===")
    print("Demonstrating unbounded growth in InMemorySessionRepository")
    
    # Create repository
    repo = LeakySessionRepository()
    
    # Create many sessions (simulating traffic over time)
    session_count = 1000
    print(f"Creating {session_count} sessions...")
    
    start_time = time.time()
    for i in range(session_count):
        session = MockSession(f"session_{i}", f"user_{i % 10}")
        repo.add(session)
        
        if i % 100 == 0:
            print(f"Created {i} sessions...")
    
    end_time = time.time()
    final_sessions = len(repo.get_all())
    
    print(f"\nResults after creating {session_count} sessions:")
    print(f"  Time taken: {end_time - start_time:.2f} seconds")
    print(f"  Final session count: {final_sessions}")
    
    # Check internal dictionaries sizes
    print(f"\nInternal state sizes (showing unbounded growth):")
    print(f"  _sessions: {len(repo._sessions)}")
    print(f"  _user_sessions: {len(repo._user_sessions)}")
    print(f"  _last_accessed: {len(repo._last_accessed)}")
    print(f"  _client_sessions: {len(repo._client_sessions)}")
    print(f"  _fingerprints: {len(repo._fingerprints)}")
    print(f"  _fingerprint_bundles: {len(repo._fingerprint_bundles)}")
    
    # Test cleanup method
    print(f"\nTesting cleanup (simulating expired sessions with max_age=0)...")
    cleaned = repo.cleanup_expired(max_age_seconds=0)
    print(f"Sessions cleaned with max_age=0: {cleaned}")
    
    remaining_sessions = len(repo.get_all())
    print(f"Sessions remaining: {remaining_sessions}")
    
    # Demonstrate the memory leak
    print(f"\n=== MEMORY LEAK ANALYSIS ===")
    if final_sessions == session_count and cleaned == 0:
        print("X MEMORY LEAK CONFIRMED:")
        print("   1. All sessions remain in memory forever")
        print("   2. No automatic cleanup (session_cleanup_enabled=False by default)")
        print("   3. Multiple dictionaries grow unbounded")
        print("   4. Each session consumes memory + tracking overhead")
        print("\n📊 Memory usage scales linearly with total sessions created")
        print("   With 10,000 daily users, memory grows indefinitely!")
        return True
    else:
        print("OK No memory leak detected.")
        return False

if __name__ == "__main__":
    leak_confirmed = main()
    exit(1 if leak_confirmed else 0)