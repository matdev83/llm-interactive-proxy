"""Repro script for ToolCallRepairProcessor._session_order memory leak.

This script demonstrates that session IDs accumulate in _session_order
when streams end without cleanup, causing unbounded memory growth.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.ports.streaming_processors import ToolCallRepairProcessor
from src.core.ports.streaming_processors import StreamingContent


def create_done_content(session_id: str) -> StreamingContent:
    """Create a [DONE] content marker."""
    content = StreamingContent(
        content="",
        metadata={"stream_id": session_id},
        stream_id=session_id,
    )
    content.is_done = True
    return content


def create_tool_call_content(session_id: str) -> StreamingContent:
    """Create content with tool calls."""
    return StreamingContent(
        content="",
        metadata={
            "stream_id": session_id,
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {"name": "test_function", "arguments": "{}"},
                }
            ],
        },
        stream_id=session_id,
    )


async def main():
    """Demonstrate the memory leak."""
    processor = ToolCallRepairProcessor(  # DI-bypass-allowed - Dev artifact repro script needs direct instantiation
        max_cached_sessions=1000
    )

    print("Creating many streams with tool calls...")
    print(f"Initial tracker count: {len(processor._session_trackers)}")
    print(f"Initial order list size: {len(processor._session_order)}")

    # Create many sessions with tool calls
    for i in range(200):
        session_id = f"session_{i}"
        content = create_tool_call_content(session_id)
        await processor.process(content)

    print("\nAfter creating 200 sessions with tool calls:")
    print(f"  Tracker count: {len(processor._session_trackers)}")
    print(f"  Order list size: {len(processor._session_order)}")

    # Now end all streams with [DONE] markers
    print("\nEnding all streams with [DONE] markers...")
    for i in range(200):
        session_id = f"session_{i}"
        done_content = create_done_content(session_id)
        await processor.process(done_content)

    print("\nAfter ending all streams:")
    print(f"  Tracker count: {len(processor._session_trackers)}")
    print(f"  Order list size: {len(processor._session_order)}")

    # Check if sessions were cleaned up
    if len(processor._session_order) == 200:
        print(
            "\n[MEMORY LEAK CONFIRMED] All 200 session IDs are still in _session_order!"
        )
        print("   They should have been removed when streams ended with [DONE].")
        return 1
    elif len(processor._session_order) > 0:
        print(
            f"\n[POTENTIAL LEAK] {len(processor._session_order)} session IDs remain in _session_order"
        )
        print("   after streams ended. They should be cleaned up.")
        return 1
    else:
        print("\n[OK] No leak detected - sessions were cleaned up properly.")
        return 0


if __name__ == "__main__":
    import asyncio

    exit_code = asyncio.run(main())
    sys.exit(exit_code)
