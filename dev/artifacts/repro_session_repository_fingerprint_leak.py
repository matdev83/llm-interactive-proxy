"""Repro script for InMemorySessionRepository._fingerprint_bundles memory leak.

This script demonstrates that _fingerprint_bundles can grow unbounded
if sessions are never cleaned up or cleanup is delayed.
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.domain.session import Session
from src.core.services.conversation_fingerprint_service import ConversationFingerprintBundle
from datetime import datetime, timezone


async def main():
    """Demonstrate unbounded growth of _fingerprint_bundles dict."""
    # Create repository with very long TTL so cleanup doesn't happen
    repository = InMemorySessionRepository(
        max_sessions=100000,  # Very large max
        default_ttl_seconds=86400 * 365,  # 1 year TTL - effectively never cleanup
    )
    
    print("Testing InMemorySessionRepository._fingerprint_bundles memory leak...")
    print(f"Initial size: {len(repository._fingerprint_bundles)}")
    
    # Simulate many sessions being created with fingerprint bundles
    # If cleanup never happens, these accumulate indefinitely
    for i in range(50000):
        session_id = f"session_{i}"
        session = Session(
            session_id=session_id,
            user_id=f"user_{i % 100}",  # Some users have multiple sessions
            created_at=datetime.now(timezone.utc),
            history=[],
        )
        
        await repository.add(session)
        
        # Add fingerprint bundle
        bundle = ConversationFingerprintBundle(
            session_id=session_id,
            rolling_fingerprints=frozenset([f"fp_{i}", f"fp_{i+1}"]),
        )
        await repository.update_fingerprint_bundle(session_id, bundle)
        
        if i % 5000 == 0:
            print(
                f"After {i} sessions: "
                f"{len(repository._fingerprint_bundles)} fingerprint bundles, "
                f"{len(repository._sessions)} sessions"
            )
    
    print(f"Final _fingerprint_bundles size: {len(repository._fingerprint_bundles)}")
    print(f"Final sessions size: {len(repository._sessions)}")
    
    # Check if cleanup would help
    print("\nTesting cleanup...")
    await repository.cleanup_expired(max_age_seconds=1)  # Clean up everything older than 1 second
    print(f"After cleanup: {len(repository._fingerprint_bundles)} fingerprint bundles")
    print(f"After cleanup: {len(repository._sessions)} sessions")
    
    if len(repository._fingerprint_bundles) > 0:
        print(
            "Memory leak confirmed: _fingerprint_bundles persists even after "
            "sessions should be expired if cleanup is not called regularly."
        )
    else:
        print("No leak: cleanup properly removes fingerprint bundles.")


if __name__ == "__main__":
    asyncio.run(main())
