"""Repro script for session history memory leak.

This script demonstrates that session history can grow unbounded
if sessions are never deleted or trimmed.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.domain.session import Session, SessionInteraction
from src.core.domain.session_state import SessionState


def test_session_history_growth():
    """Test that session history grows unbounded."""
    session = Session(
        id="test-session",
        session_id="test-session",
        state=SessionState(),
    )
    
    initial_history_size = len(session.history)
    print(f"Initial history size: {initial_history_size}")
    
    # Add many interactions
    num_interactions = 10000
    for i in range(num_interactions):
        interaction = SessionInteraction(
            role="user",
            content=f"Message {i}",
            timestamp=datetime.now(timezone.utc),
        )
        session.add_interaction(interaction)
    
    final_history_size = len(session.history)
    print(f"Final history size: {final_history_size}")
    print(f"Expected: {initial_history_size + num_interactions}")
    
    if final_history_size == initial_history_size + num_interactions:
        print("❌ MEMORY LEAK CONFIRMED: Session history grows unbounded!")
        print(f"   No limit on history size - can grow to {final_history_size} entries")
        return True
    else:
        print("✓ History size matches expected")
        return False


def test_multiple_sessions_history_growth():
    """Test that multiple sessions can accumulate unbounded history."""
    sessions = []
    num_sessions = 100
    interactions_per_session = 1000
    
    print(f"\nCreating {num_sessions} sessions with {interactions_per_session} interactions each...")
    
    for session_idx in range(num_sessions):
        session = Session(
            id=f"session-{session_idx}",
            session_id=f"session-{session_idx}",
            state=SessionState(),
        )
        
        for i in range(interactions_per_session):
            interaction = SessionInteraction(
                role="user",
                content=f"Message {i}",
                timestamp=datetime.now(timezone.utc),
            )
            session.add_interaction(interaction)
        
        sessions.append(session)
    
    total_interactions = sum(len(s.history) for s in sessions)
    print(f"Total interactions across all sessions: {total_interactions}")
    print(f"Expected: {num_sessions * interactions_per_session}")
    
    if total_interactions == num_sessions * interactions_per_session:
        print("❌ MEMORY LEAK CONFIRMED: Multiple sessions accumulate unbounded history!")
        print(f"   Total memory usage: {total_interactions} interaction objects")
        return True
    else:
        print("✓ Total interactions match expected")
        return False


def main():
    """Run all leak tests."""
    print("=" * 60)
    print("Testing Session History Memory Leaks")
    print("=" * 60)
    
    leak1 = test_session_history_growth()
    leak2 = test_multiple_sessions_history_growth()
    
    print("\n" + "=" * 60)
    if leak1 or leak2:
        print("RESULT: Memory leaks confirmed!")
        sys.exit(1)
    else:
        print("RESULT: No leaks detected")
        sys.exit(0)


if __name__ == "__main__":
    main()
