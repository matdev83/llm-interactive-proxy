"""Regression tests for tool call loop safety primitives.

This test ensures that when multiple async tasks try to access the same
registry concurrently, only one task at a time can enter the critical section.
"""

import asyncio

import pytest
from src.tool_call_loop.lifecycle_registry import ToolCallLifecycleRegistry


@pytest.mark.asyncio
async def test_concurrent_access_is_protected():
    """Verify that concurrent registrations allow only one first-time detection."""
    registry = ToolCallLifecycleRegistry(max_streams=10)
    stream_key = "test-stream"
    signature = "test-sig"

    completed_count = 0

    async def try_register():
        nonlocal completed_count

        if await registry.register_detection(stream_key, signature):
            completed_count += 1

    async def try_register_early_exit():
        nonlocal completed_count

        if await registry.register_detection(stream_key, signature):
            completed_count += 1

    launch_tasks = [
        asyncio.create_task(try_register()),
        asyncio.create_task(try_register()),
        asyncio.create_task(try_register()),
    ]

    await asyncio.gather(*launch_tasks, return_exceptions=True)

    assert completed_count == 1, (
        f"Expected only 1 successful registration, got {completed_count}. "
        "This proves duplicate detection is prevented."
    )


@pytest.mark.asyncio
async def test_tracker_sync_methods():
    """Verify ToolCallTracker can track tool calls."""
    from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode
    from src.tool_call_loop.tracker import ToolCallTracker

    tracker = ToolCallTracker(
        config=ToolCallLoopConfig(
            enabled=True,
            max_repeats=4,
            ttl_seconds=120,
            mode=ToolLoopMode.BREAK,
        )
    )

    result = tracker.track_tool_call("test_tool", '{"arg": "value"}')

    assert hasattr(result, "should_block")
    assert result.should_block is False
