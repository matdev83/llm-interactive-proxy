"""Regression test for ToolCallLifecycleRegistry race condition fix.

Tests that ToolCallStreamState sets (inflight_signatures, processed_signatures)
are properly protected by the threading.Lock.
"""

import asyncio

import pytest
from src.tool_call_loop.lifecycle_registry import (
    ToolCallLifecycleRegistry,
)


@pytest.mark.asyncio
async def test_lifecycle_registry_concurrent_register():
    """Test concurrent register_detection operations are properly synchronized."""
    registry = ToolCallLifecycleRegistry(max_streams=10)
    stream_key = "test-stream"
    signature = "test-signature-001"

    # Track successful registrations
    successful_count = [0]

    async def register_task(task_id: int):
        """Try to register the same signature from multiple tasks"""
        result = await registry.register_detection(stream_key, signature)
        if result:
            successful_count[0] += 1

    # Launch concurrent registrations for the SAME signature
    # Only ONE should succeed due to lock protection
    tasks = [register_task(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # Only first registration should succeed (others see signature already in flight)
    # Lock ensures this happens atomically
    assert (
        successful_count[0] == 1
    ), f"Expected 1 successful registration, got {successful_count[0]}"


@pytest.mark.asyncio
async def test_lifecycle_registry_register_then_mark():
    """Test that register -> mark_processed sequence is atomic."""
    registry = ToolCallLifecycleRegistry(max_streams=10)
    stream_key = "test-stream-2"
    signature = "test-signature-002"

    # Register signature
    assert await registry.register_detection(stream_key, signature) is True

    # Mark as processed
    await registry.mark_processed(stream_key, signature)

    # Register again - should now FAIL since it's already processed
    # (it was moved to processed)
    assert await registry.register_detection(stream_key, signature) is False

    # Should be marked as processed
    assert await registry.is_processed(stream_key, signature) is True


@pytest.mark.asyncio
async def test_lifecycle_registry_multiple_streams():
    """Test that different stream keys have independent state."""
    registry = ToolCallLifecycleRegistry(max_streams=10)

    results = []

    async def register_for_stream(stream_id: int):
        """Register a signature for a specific stream"""
        result = await registry.register_detection(
            f"stream-{stream_id}", f"sig-{stream_id}"
        )
        results.append(result)

    # Register for 5 different streams concurrently
    tasks = [register_for_stream(i) for i in range(5)]
    await asyncio.gather(*tasks)

    # All registrations should succeed (different streams)
    assert all(results), "All registrations for different streams should succeed"
    assert len(results) == 5


@pytest.mark.asyncio
async def test_lifecycle_registry_clear_stream():
    """Test that clear_stream properly cleans up state."""
    registry = ToolCallLifecycleRegistry(max_streams=10)
    stream_key = "test-stream-3"

    # Register some signatures
    for i in range(3):
        await registry.register_detection(stream_key, f"sig-{i}")

    # Clear the stream
    await registry.clear_stream(stream_key)

    # After clear, should be able to register the same signatures again
    assert await registry.register_detection(stream_key, "sig-0") is True
    assert await registry.register_detection(stream_key, "sig-1") is True


if __name__ == "__main__":
    # Run tests directly
    asyncio.run(test_lifecycle_registry_concurrent_register())
    asyncio.run(test_lifecycle_registry_register_then_mark())
    asyncio.run(test_lifecycle_registry_multiple_streams())
    asyncio.run(test_lifecycle_registry_clear_stream())
    print("All regression tests passed!")
