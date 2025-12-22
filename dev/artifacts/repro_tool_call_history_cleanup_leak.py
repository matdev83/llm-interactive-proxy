"""Repro script for ToolCallHistoryTracker cleanup memory leak.

This script demonstrates that when max_sessions limit is exceeded,
sessions are not properly removed from _history dict, causing unbounded growth.
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.tool_call_reactor_service import InMemoryToolCallHistoryTracker


async def main():
    """Demonstrate the memory leak."""
    # Create tracker with small max_sessions to trigger cleanup
    tracker = InMemoryToolCallHistoryTracker(
        session_ttl_seconds=3600,
        max_sessions=10,  # Small limit to trigger cleanup
        max_entries_per_session=100,
    )

    print("Creating sessions beyond max_sessions limit...")
    print(f"Max sessions: {tracker._max_sessions}")
    print(f"Initial history count: {len(tracker._history)}")

    # Create more sessions than max_sessions
    for i in range(20):
        session_id = f"session_{i}"
        await tracker.record_tool_call(
            session_id,
            "test_tool",
            {
                "timestamp": datetime.now(timezone.utc),
                "backend_name": "test",
                "model_name": "test",
            },
        )

    print(f"\nAfter creating 20 sessions:")
    print(f"  History count: {len(tracker._history)}")
    print(f"  Expected max: {tracker._max_sessions}")

    # Wait a bit for any async cleanup
    await asyncio.sleep(0.5)

    # Manually trigger cleanup
    async with tracker._lock:
        await tracker._cleanup_expired_sessions_locked()

    print(f"\nAfter cleanup:")
    print(f"  History count: {len(tracker._history)}")
    print(f"  Expected max: {tracker._max_sessions}")

    if len(tracker._history) > tracker._max_sessions:
        print(
            f"\n[MEMORY LEAK CONFIRMED] History has {len(tracker._history)} sessions, "
            f"exceeding max of {tracker._max_sessions}!"
        )
        print("   Sessions should have been removed when max limit was exceeded.")
        return 1
    else:
        print("\n[OK] No leak detected - sessions were cleaned up properly.")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
