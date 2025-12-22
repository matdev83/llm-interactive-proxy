"""Repro script to demonstrate unbounded memory growth in ModelReplacementService.

This script simulates many sessions being created and used, showing that
_session_states and _disabled_sessions dictionaries grow without bounds
because cleanup_session() is never called.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.services.model_replacement_service import ModelReplacementService
from src.core.services.backend_registry import BackendRegistry


class MockBackendRegistry:
    """Mock backend registry for testing."""

    def get_registered_backends(self):
        return ["openai", "gemini"]


async def main():
    """Demonstrate unbounded memory growth."""
    print("=" * 80)
    print("ModelReplacementService Memory Leak Repro")
    print("=" * 80)
    print()

    # Create config
    config = ReplacementConfig(
        enabled=True,
        probability=0.5,
        backend_model="gemini:gemini-pro",
        turn_count=3,
    )

    # Create service
    registry = MockBackendRegistry()
    service = ModelReplacementService(config, registry)

    print(f"Initial state:")
    print(f"  _session_states size: {len(service._session_states)}")
    print(f"  _disabled_sessions size: {len(service._disabled_sessions)}")
    print()

    # Simulate many sessions
    num_sessions = 1000
    print(f"Simulating {num_sessions} sessions...")
    print()

    # Create a minimal mock RequestContext
    class MockRequestContext:
        def get_header(self, name, default=""):
            return default

    ctx = MockRequestContext()

    for i in range(num_sessions):
        session_id = f"session-{i:04d}"

        # Create state by calling should_replace
        service.should_replace(session_id, ctx)

        # Some sessions get disabled
        if i % 10 == 0:
            service.disable_for_session(session_id)

        # Some sessions activate replacement
        if i % 5 == 0:
            await service.activate_replacement(session_id, "openai", "gpt-4")

        # Progress indicator
        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1} sessions...")

    print()
    print(f"After {num_sessions} sessions:")
    print(f"  _session_states size: {len(service._session_states)}")
    print(f"  _disabled_sessions size: {len(service._disabled_sessions)}")
    print()

    # Simulate sessions ending (but cleanup_session is never called)
    print("Sessions end, but cleanup_session() is NEVER called!")
    print()

    # Show that state persists
    print(f"State still persists:")
    print(f"  _session_states size: {len(service._session_states)}")
    print(f"  _disabled_sessions size: {len(service._disabled_sessions)}")
    print()

    # Show memory usage estimate
    import sys

    # Rough estimate: each session state ~200 bytes, disabled session ID ~50 bytes
    estimated_bytes = (
        len(service._session_states) * 200 + len(service._disabled_sessions) * 50
    )
    print(f"Estimated memory usage: ~{estimated_bytes:,} bytes (~{estimated_bytes / 1024:.1f} KB)")
    print()

    print("=" * 80)
    print("MEMORY LEAK CONFIRMED:")
    print("  - _session_states grows without bounds")
    print("  - _disabled_sessions grows without bounds")
    print("  - cleanup_session() exists but is never called")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
