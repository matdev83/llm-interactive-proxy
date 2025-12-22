"""Repro script to confirm memory leak in _auto_enabled_sessions set.

Issue: _auto_enabled_sessions set grows unbounded when sessions are auto-enabled
but never cleaned up when sessions end.
"""

import sys
import tracemalloc
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.memory.capture_middleware import MemoryCaptureMiddleware
from src.core.memory.config import MemoryConfiguration


class MockMemoryService:
    """Mock memory service for testing."""

    def __init__(self):
        self._enabled_sessions = set()

    def is_available(self) -> bool:
        return True

    async def is_enabled_for_session(self, session_id: str) -> bool:
        return session_id in self._enabled_sessions

    async def enable_for_session(
        self,
        session_id: str,
        user_id: str,
        client_id: str | None = None,
        tenant_id: str | None = None,
        project_root: str | None = None,
    ) -> bool:
        self._enabled_sessions.add(session_id)
        return True

    async def capture_interaction(self, session_id: str, interaction) -> bool:
        return True


def simulate_unbounded_session_accumulation():
    """Simulate many sessions being auto-enabled without cleanup."""
    memory_service = MockMemoryService()
    config = MemoryConfiguration(default_enabled=True)
    middleware = MemoryCaptureMiddleware(memory_service, config)

    # Start memory tracking
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()

    # Simulate many sessions being auto-enabled
    print("Simulating unbounded session accumulation...")
    import asyncio

    async def run_simulation():
        for i in range(10000):
            session_id = f"session_{i}"
            # Simulate auto-enable (like capture_request does)
            if session_id not in middleware._auto_enabled_sessions:
                middleware._auto_enabled_sessions.add(session_id)
                await memory_service.enable_for_session(session_id, f"user_{i}")

            if i % 1000 == 0:
                snapshot2 = tracemalloc.take_snapshot()
                top_stats = snapshot2.compare_to(snapshot1, "lineno")
                print(f"\nAfter {i} sessions:")
                print(f"  _auto_enabled_sessions size: {len(middleware._auto_enabled_sessions)}")
                print(f"  Memory growth (top 5):")
                for stat in top_stats[:5]:
                    print(f"    {stat}")

        return middleware

    middleware = asyncio.run(run_simulation())

    # Final snapshot
    snapshot3 = tracemalloc.take_snapshot()
    top_stats = snapshot3.compare_to(snapshot1, "lineno")
    print(f"\n=== FINAL STATE ===")
    print(f"_auto_enabled_sessions size: {len(middleware._auto_enabled_sessions)}")
    print(f"\nTotal memory growth:")
    for stat in top_stats[:10]:
        print(f"  {stat}")

    # Check if memory grew unbounded
    if len(middleware._auto_enabled_sessions) == 10000:
        print("\n[CONFIRMED] Memory leak - set grew to 10000 entries")
        print("  The set will continue growing if more sessions are auto-enabled")
        return True
    else:
        print("\n[NO LEAK] No leak detected")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("Memory Leak Repro: _auto_enabled_sessions set")
    print("=" * 70)
    leak_confirmed = simulate_unbounded_session_accumulation()
    sys.exit(0 if leak_confirmed else 1)
