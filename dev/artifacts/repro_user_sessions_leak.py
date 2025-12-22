"""Repro script for user_sessions memory leak in InMemorySessionRepository.

This script demonstrates that _user_sessions lists can grow unbounded
if a single user creates many sessions.
"""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.domain.session import Session, SessionState


async def test_user_sessions_unbounded_growth():
    """Test that _user_sessions lists grow unbounded for a single user."""
    repo = InMemorySessionRepository(max_sessions=100000)  # High limit to avoid eviction
    
    user_id = "test-user"
    num_sessions = 10000
    
    print(f"Creating {num_sessions} sessions for user '{user_id}'...")
    
    # Create many sessions for the same user
    for i in range(num_sessions):
        session = Session(
            session_id=f"session-{i}",
            state=SessionState(),
        )
        # Set user_id
        session.user_id = user_id
        
        await repo.add(session)
    
    # Check the size of the user's session list
    user_session_list = repo._user_sessions.get(user_id, [])
    print(f"Number of sessions in _user_sessions['{user_id}']: {len(user_session_list)}")
    print(f"Expected: {num_sessions}")
    
    if len(user_session_list) == num_sessions:
        print("MEMORY LEAK CONFIRMED: _user_sessions list grows unbounded!")
        print(f"   Single user can accumulate {len(user_session_list)} session IDs")
        print("   No limit on sessions per user - can grow indefinitely")
        return True
    else:
        print(f"Unexpected: list size is {len(user_session_list)}, expected {num_sessions}")
        return False


async def test_client_sessions_unbounded_growth():
    """Test that _client_sessions lists grow unbounded for a single client."""
    repo = InMemorySessionRepository(max_sessions=100000)
    
    client_key = "test-client"
    num_sessions = 10000
    
    print(f"\nCreating {num_sessions} sessions for client '{client_key}'...")
    
    # Create many sessions for the same client
    for i in range(num_sessions):
        session = Session(
            session_id=f"session-{i}",
            state=SessionState(),
        )
        
        await repo.add(session)
        await repo.update_client_session(f"session-{i}", client_key)
    
    # Check the size of the client's session list
    client_session_list = repo._client_sessions.get(client_key, [])
    print(f"Number of sessions in _client_sessions['{client_key}']: {len(client_session_list)}")
    print(f"Expected: {num_sessions}")
    
    if len(client_session_list) == num_sessions:
        print("MEMORY LEAK CONFIRMED: _client_sessions list grows unbounded!")
        print(f"   Single client can accumulate {len(client_session_list)} session IDs")
        print("   No limit on sessions per client - can grow indefinitely")
        return True
    else:
        print(f"Unexpected: list size is {len(client_session_list)}, expected {num_sessions}")
        return False


async def test_session_history_unbounded_growth():
    """Test that session history grows unbounded."""
    repo = InMemorySessionRepository(max_sessions=100000)
    
    from src.core.domain.session import SessionInteraction
    from datetime import datetime, timezone
    
    session = Session(
        session_id="test-session",
        state=SessionState(),
    )
    
    await repo.add(session)
    
    num_interactions = 50000
    
    print(f"\nAdding {num_interactions} interactions to session...")
    
    for i in range(num_interactions):
        interaction = SessionInteraction(
            role="user",
            content=f"Message {i}",
            timestamp=datetime.now(timezone.utc),
        )
        session.add_interaction(interaction)
    
    # Update session in repo
    await repo.update(session)
    
    # Get session back
    retrieved = await repo.get_by_id("test-session")
    if retrieved:
        history_size = len(retrieved.history)
        print(f"Session history size: {history_size}")
        print(f"Expected: {num_interactions}")
        
        if history_size == num_interactions:
            print("MEMORY LEAK CONFIRMED: Session history grows unbounded!")
            print(f"   Single session can accumulate {history_size} interactions")
            print("   No limit on history size - can grow indefinitely")
            return True
    
    return False


async def main():
    """Run all leak tests."""
    print("=" * 60)
    print("Testing InMemorySessionRepository Memory Leaks")
    print("=" * 60)
    
    leak1 = await test_user_sessions_unbounded_growth()
    leak2 = await test_client_sessions_unbounded_growth()
    leak3 = await test_session_history_unbounded_growth()
    
    print("\n" + "=" * 60)
    if leak1 or leak2 or leak3:
        print("RESULT: Memory leaks confirmed!")
        sys.exit(1)
    else:
        print("RESULT: No leaks detected")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
