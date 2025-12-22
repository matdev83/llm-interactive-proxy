"""Repro script to test SessionCaptureBuffer memory leak.

This script tests if SessionCaptureBuffer accumulates buffers without cleanup,
leading to unbounded memory growth.
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


async def test_unbounded_growth():
    """Test that SessionCaptureBuffer grows unbounded without cleanup."""
    buffer = SessionCaptureBuffer(max_buffer_size_bytes=1024 * 1024)  # 1MB per session
    
    # Simulate creating many sessions without cleanup
    num_sessions = 10000
    print(f"Creating {num_sessions} sessions without cleanup...")
    
    for i in range(num_sessions):
        session_id = f"session_{i}"
        interaction = CapturedInteraction(
            timestamp=datetime.now(timezone.utc),
            content=f"Test content for session {i}",
            role="user",
            metadata={"session": session_id}
        )
        await buffer.append(session_id, interaction)
        
        if (i + 1) % 1000 == 0:
            active_count = await buffer.get_active_session_count()
            print(f"After {i + 1} sessions: {active_count} active buffers")
    
    final_count = await buffer.get_active_session_count()
    print(f"\nFinal active session count: {final_count}")
    print(f"Expected: {num_sessions}")
    
    if final_count == num_sessions:
        print("❌ MEMORY LEAK CONFIRMED: All sessions remain in memory!")
        print("   SessionCaptureBuffer._buffers dict grows unbounded")
        print("   without automatic cleanup of old sessions.")
        return True
    else:
        print(f"✓ No leak detected (unexpected: got {final_count} instead of {num_sessions})")
        return False


if __name__ == "__main__":
    leak_confirmed = asyncio.run(test_unbounded_growth())
    sys.exit(1 if leak_confirmed else 0)
