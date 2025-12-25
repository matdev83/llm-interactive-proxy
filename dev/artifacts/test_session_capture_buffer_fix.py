"""Test script to verify SessionCaptureBuffer memory leak fix.

This script verifies that SessionCaptureBuffer no longer grows unbounded
with the TTL-based cleanup and max_sessions limit.
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.models import CapturedInteraction


async def test_max_sessions_limit():
    """Test that max_sessions limit prevents unbounded growth."""
    max_sessions = 100
    buffer = SessionCaptureBuffer(
        max_buffer_size_bytes=1024 * 1024,  # 1MB per session
        max_sessions=max_sessions,
        session_ttl_seconds=3600,  # 1 hour
    )

    # Create more sessions than the limit
    num_sessions = max_sessions + 50
    print(f"Creating {num_sessions} sessions (max_sessions={max_sessions})...")

    for i in range(num_sessions):
        session_id = f"session_{i}"
        interaction = CapturedInteraction(
            timestamp=datetime.now(timezone.utc),
            content=f"Test content for session {i}",
            role="user",
            metadata={"session": session_id},
        )
        await buffer.append(session_id, interaction)

        if (i + 1) % 20 == 0:
            active_count = await buffer.get_active_session_count()
            print(f"After {i + 1} sessions: {active_count} active buffers")

    final_count = await buffer.get_active_session_count()
    print(f"\nFinal active session count: {final_count}")
    print(f"Max sessions limit: {max_sessions}")

    if final_count <= max_sessions:
        print("[PASS] Session count is bounded by max_sessions limit")
        return True
    else:
        print(f"[FAIL] Session count ({final_count}) exceeds limit ({max_sessions})")
        return False


async def test_ttl_cleanup():
    """Test that TTL-based cleanup removes expired sessions."""
    ttl_seconds = 1  # Very short TTL for testing
    buffer = SessionCaptureBuffer(
        max_buffer_size_bytes=1024 * 1024,
        max_sessions=1000,
        session_ttl_seconds=ttl_seconds,
    )

    # Create some sessions
    num_sessions = 10
    print(f"\nCreating {num_sessions} sessions with TTL={ttl_seconds}s...")

    for i in range(num_sessions):
        session_id = f"session_{i}"
        interaction = CapturedInteraction(
            timestamp=datetime.now(timezone.utc),
            content=f"Test content for session {i}",
            role="user",
            metadata={"session": session_id},
        )
        await buffer.append(session_id, interaction)

    initial_count = await buffer.get_active_session_count()
    print(f"Initial session count: {initial_count}")

    # Wait for TTL to expire
    print(f"Waiting {ttl_seconds + 1} seconds for TTL expiration...")
    await asyncio.sleep(ttl_seconds + 1)

    # Access buffer to trigger cleanup
    await buffer.get_active_session_count()
    final_count = await buffer.get_active_session_count()
    print(f"Final session count after TTL expiration: {final_count}")

    if final_count == 0:
        print("[PASS] All expired sessions were cleaned up")
        return True
    else:
        print(f"[FAIL] {final_count} sessions still remain (expected 0)")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing SessionCaptureBuffer memory leak fix")
    print("=" * 60)

    test1_passed = await test_max_sessions_limit()
    test2_passed = await test_ttl_cleanup()

    print("\n" + "=" * 60)
    if test1_passed and test2_passed:
        print("[PASS] ALL TESTS PASSED: Memory leak fix is working correctly")
        return 0
    else:
        print("[FAIL] SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
