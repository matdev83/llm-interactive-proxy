"""
Repro script to demonstrate memory leak in ToolCallReactorService._session_aliases.

The _session_aliases dictionary grows unbounded without any cleanup mechanism.
Each unique session_id creates a new entry that is never removed.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.tool_call_reactor_service import ToolCallReactorService
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from datetime import datetime, timezone


async def test_session_aliases_leak():
    """Test that _session_aliases grows unbounded."""
    reactor = (
        ToolCallReactorService()  # noqa: DI-bypass - Dev artifact repro script needs direct instantiation
    )

    # Check if _session_aliases exists (it shouldn't be initialized)
    if not hasattr(reactor, "_session_aliases"):
        print("[CONFIRMED] _session_aliases is not initialized in __init__")
        print("  This will cause AttributeError when first accessed with session_id")
        print("\nTesting if code path is actually executed...")

        # Try to trigger the code path
        context = ToolCallContext(
            session_id="test_session_123",  # Non-None session_id
            backend_name="test_backend",
            model_name="test_model",
            full_response=None,
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
            calling_agent="test_agent",
            timestamp=datetime.now(timezone.utc),
        )

        try:
            await reactor.process_tool_call(context)
            print("  ERROR: Code executed without AttributeError!")
            print("  This suggests _session_aliases might be created dynamically")
        except AttributeError as e:
            print(f"  [CONFIRMED] AttributeError raised: {e}")
            print("  This confirms the bug - _session_aliases is not initialized")

        # Now initialize it manually to test the memory leak
        print("\nInitializing _session_aliases manually to test memory leak...")
        reactor._session_aliases = {}

    # Simulate many unique sessions
    num_sessions = 10000
    print(f"\nCreating {num_sessions} unique sessions...")

    for i in range(num_sessions):
        context = ToolCallContext(
            session_id=f"session_{i}",
            backend_name="test_backend",
            model_name="test_model",
            full_response=None,
            tool_name="test_tool",
            tool_arguments={"arg": f"value_{i}"},
            calling_agent="test_agent",
            timestamp=datetime.now(timezone.utc),
        )

        await reactor.process_tool_call(context)

    # Check memory growth
    if hasattr(reactor, "_session_aliases"):
        size = len(reactor._session_aliases)
        print(f"\nAfter {num_sessions} sessions:")
        print(f"  _session_aliases size: {size}")
        print(f"  Expected: {num_sessions}")

        if size == num_sessions:
            print("\n[CONFIRMED] _session_aliases grows unbounded")
            print("  - No cleanup mechanism")
            print("  - No size limit")
            print("  - No TTL")
            print("  - Each unique session_id creates permanent entry")
            print("\n  MEMORY LEAK CONFIRMED!")
        else:
            print(f"\n  Unexpected size: {size} (expected {num_sessions})")
    else:
        print("\nERROR: _session_aliases still doesn't exist after processing")


if __name__ == "__main__":
    asyncio.run(test_session_aliases_leak())
