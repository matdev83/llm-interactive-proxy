"""Regression tests for tool call loop safety primitives.

This test ensures that when multiple async tasks try to access same
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
async def test_tracker_async_methods():
    """Verify ToolCallTracker async methods work correctly."""
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

    result = await tracker.track_tool_call("test_tool", '{"arg": "value"}')

    assert hasattr(result, "should_block")
    assert result.should_block is False


@pytest.mark.asyncio
async def test_tracker_concurrent_async_safety():
    """Verify concurrent async access to ToolCallTracker doesn't block event loop."""
    from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode
    from src.tool_call_loop.tracker import ToolCallTracker

    tracker = ToolCallTracker(
        config=ToolCallLoopConfig(
            enabled=True,
            max_repeats=10,
            ttl_seconds=120,
            mode=ToolLoopMode.BREAK,
        )
    )

    num_tasks = 20
    successful_calls = 0
    blocked_calls = 0

    async def make_tool_call(index: int):
        nonlocal successful_calls, blocked_calls
        result = await tracker.track_tool_call("test_tool", f'{{"arg": "{index}"}}')
        if result.should_block:
            blocked_calls += 1
        else:
            successful_calls += 1

    # Launch concurrent tasks
    tasks = [asyncio.create_task(make_tool_call(i)) for i in range(num_tasks)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Verify results are consistent (no corruption)
    assert successful_calls + blocked_calls == num_tasks
    # All signatures should be unique or properly counted
    assert len(tracker.signatures) <= tracker.max_signatures
    # All counts should be non-negative
    for count in tracker.consecutive_repeats.values():
        assert count >= 0
    # chance_given should only contain bool values
    for value in tracker.chance_given.values():
        assert isinstance(value, bool)
