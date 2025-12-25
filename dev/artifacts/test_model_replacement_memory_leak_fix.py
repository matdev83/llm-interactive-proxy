"""Test script to verify ModelReplacementService memory leak fix.

This script verifies that _session_states and _disabled_sessions are bounded
and evict old entries when limits are exceeded.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.services.model_replacement_service import (
    MAX_DISABLED_SESSIONS,
    MAX_SESSION_STATES,
    ModelReplacementService,
)


class MockBackendRegistry:
    """Mock backend registry for testing."""

    def get_registered_backends(self):
        return ["openai", "gemini"]


async def main():
    """Test that memory leak is fixed with size limits."""
    print("=" * 80)
    print("ModelReplacementService Memory Leak Fix Verification")
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

    print("Size limits:")
    print(f"  MAX_SESSION_STATES: {MAX_SESSION_STATES}")
    print(f"  MAX_DISABLED_SESSIONS: {MAX_DISABLED_SESSIONS}")
    print()

    print("Initial state:")
    print(f"  _session_states size: {len(service._session_states)}")
    print(f"  _disabled_sessions size: {len(service._disabled_sessions)}")
    print()

    # Create a minimal mock RequestContext
    class MockRequestContext:
        def get_header(self, name, default=""):
            return default

    ctx = MockRequestContext()

    # Create MORE sessions than the limit to trigger eviction
    num_sessions = MAX_SESSION_STATES + 500
    print(f"Creating {num_sessions} sessions (exceeds limit of {MAX_SESSION_STATES})...")
    print()

    for i in range(num_sessions):
        session_id = f"session-{i:08d}"

        # Create state by calling should_replace
        service.should_replace(session_id, ctx)

        # Some sessions get disabled
        if i % 10 == 0:
            service.disable_for_session(session_id)

        # Some sessions activate replacement (but complete turns to make them inactive)
        if i % 5 == 0:
            await service.activate_replacement(session_id, "openai", "gpt-4")
            # Complete all turns to make them inactive (so they can be evicted)
            for _ in range(3):
                service.complete_turn(session_id)

        # Progress indicator
        if (i + 1) % 500 == 0:
            current_size = len(service._session_states)
            print(f"  Processed {i + 1} sessions, current _session_states size: {current_size}")

    print()
    print(f"After creating {num_sessions} sessions:")
    final_states_size = len(service._session_states)
    final_disabled_size = len(service._disabled_sessions)
    print(f"  _session_states size: {final_states_size}")
    print(f"  _disabled_sessions size: {final_disabled_size}")
    print()

    # Verify size limits are enforced
    states_ok = final_states_size <= MAX_SESSION_STATES
    disabled_ok = final_disabled_size <= MAX_DISABLED_SESSIONS

    print("=" * 80)
    if states_ok and disabled_ok:
        print("[OK] FIX VERIFIED:")
        print(f"  - _session_states is bounded: {final_states_size} <= {MAX_SESSION_STATES}")
        print(f"  - _disabled_sessions is bounded: {final_disabled_size} <= {MAX_DISABLED_SESSIONS}")
        print("  - Memory leak is fixed!")
    else:
        print("[FAIL] FIX FAILED:")
        if not states_ok:
            print(f"  - _session_states exceeds limit: {final_states_size} > {MAX_SESSION_STATES}")
        if not disabled_ok:
            print(
                f"  - _disabled_sessions exceeds limit: {final_disabled_size} > {MAX_DISABLED_SESSIONS}"
            )
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
