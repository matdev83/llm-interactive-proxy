"""Repro script to test InMemorySessionRepository auxiliary structures leak.

This script tests if auxiliary structures (_user_sessions, _client_sessions,
_fingerprint_bundles) accumulate without bounds when sessions accumulate.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.domain.session import Session
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository


async def main() -> None:
    """Test InMemorySessionRepository auxiliary structure accumulation."""
    repo = InMemorySessionRepository(max_sessions=1000, default_ttl_seconds=3600)

    print("Testing InMemorySessionRepository auxiliary structure accumulation...")
    print("=" * 60)

    # Create many sessions with user IDs and client keys
    num_sessions = 2000  # More than max_sessions to test eviction
    print(f"Creating {num_sessions} sessions (max_sessions={repo._max_sessions})...")

    for i in range(num_sessions):
        session = Session(
            session_id=f"session-{i}",
            user_id=f"user-{i % 100}",  # 100 unique users
            history=[],
        )
        await repo.add(session)

        # Update fingerprint and client session
        await repo.update_fingerprint(f"session-{i}", f"fingerprint-{i}")
        await repo.update_client_session(f"session-{i}", f"client-{i % 50}")  # 50 unique clients

        if (i + 1) % 500 == 0:
            print(f"  Created {i + 1} sessions")
            print(f"    _sessions size: {len(repo._sessions)}")
            print(f"    _user_sessions size: {len(repo._user_sessions)}")
            print(f"    _client_sessions size: {len(repo._client_sessions)}")
            print(f"    _fingerprints size: {len(repo._fingerprints)}")
            print(f"    _fingerprint_bundles size: {len(repo._fingerprint_bundles)}")

    # Check final sizes
    print(f"\nFinal sizes:")
    print(f"  _sessions: {len(repo._sessions)}")
    print(f"  _user_sessions: {len(repo._user_sessions)}")
    print(f"  _client_sessions: {len(repo._client_sessions)}")
    print(f"  _fingerprints: {len(repo._fingerprints)}")
    print(f"  _fingerprint_bundles: {len(repo._fingerprint_bundles)}")

    # Count total entries in auxiliary structures
    total_user_sessions = sum(len(sessions) for sessions in repo._user_sessions.values())
    total_client_sessions = sum(len(sessions) for sessions in repo._client_sessions.values())

    print(f"\nTotal entries in auxiliary structures:")
    print(f"  Total session IDs in _user_sessions: {total_user_sessions}")
    print(f"  Total session IDs in _client_sessions: {total_client_sessions}")

    # Check if auxiliary structures exceed main sessions
    if len(repo._fingerprints) > len(repo._sessions) or len(repo._fingerprint_bundles) > len(repo._sessions):
        print("\n[CONFIRMED] Auxiliary structures can exceed main session count")
        print("  Issue: _fingerprints and _fingerprint_bundles don't have explicit limits")
        print("  Risk: If sessions are evicted but auxiliary structures aren't cleaned up,")
        print("        memory usage grows unbounded")
    elif total_user_sessions > len(repo._sessions) or total_client_sessions > len(repo._sessions):
        print("\n[CONFIRMED] Auxiliary structures can exceed main session count")
        print("  Issue: _user_sessions and _client_sessions can accumulate entries")
        print("  Risk: If sessions are evicted but auxiliary structures aren't cleaned up,")
        print("        memory usage grows unbounded")
    else:
        print("\n[Auxiliary structures appear to be cleaned up properly]")


if __name__ == "__main__":
    asyncio.run(main())
