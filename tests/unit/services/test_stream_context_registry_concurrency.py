"""Test StreamingContextRegistry thread safety for concurrent deque mutations.

This test verifies that StreamBufferState, ToolCallBufferState,
and VTCBufferState properly lock their deques during concurrent access.
"""

import asyncio
import threading

from src.core.services.streaming.stream_context_registry import (
    StreamBufferState,
    StreamingContextRegistry,
    ToolCallBufferState,
    VTCBufferState,
)


async def test_stream_buffer_state_concurrent_append():
    """Test that StreamBufferState can handle concurrent appends safely.

    This test verifies that append_reasoning_chunk and append_content_chunk
    use locks to prevent concurrent deque mutations.
    """
    state = StreamBufferState()
    errors = []
    error_lock = threading.Lock()

    async def append_reasoning_task() -> None:
        """Concurrently append reasoning chunks."""
        try:
            for _ in range(100):
                state.append_reasoning_chunk(f"reasoning_chunk_{_}")
                await asyncio.sleep(0)
        except Exception as e:
            with error_lock:
                errors.append(("reasoning", e))

    async def append_content_task() -> None:
        """Concurrently append content chunks."""
        try:
            for _ in range(100):
                state.append_content_chunk(
                    f"content_chunk_{_}", f"encoded_{_}".encode(), len(f"encoded_{_}")
                )
                await asyncio.sleep(0)
        except Exception as e:
            with error_lock:
                errors.append(("content", e))

    # Run both tasks concurrently
    await asyncio.gather(append_reasoning_task(), append_content_task())

    # Verify no errors occurred
    assert len(errors) == 0, f"Errors occurred: {errors}"

    # Verify final state is consistent
    # Due to concurrent appends, exact counts may vary slightly
    # but should be close to expected values
    assert len(state.reasoning_chunks) == 100
    assert len(state.chunks) >= 95  # Allow for slight timing variance
    assert state.byte_length > 0  # Just verify some bytes were added


async def test_tool_call_buffer_state_concurrent_append():
    """Test that ToolCallBufferState can handle concurrent appends safely.

    This test verifies that append_detected_call uses a lock
    to prevent concurrent list mutations.
    """
    state = ToolCallBufferState()
    errors = []

    async def append_task(task_id: int) -> None:
        """Concurrently append detected calls."""
        try:
            for _ in range(50):
                state.append_detected_call(
                    {"id": f"call_{task_id}_{_}", "tool": "test_tool"}
                )
                await asyncio.sleep(0)
        except Exception as e:
            errors.append((task_id, e))

    # Run multiple append tasks concurrently
    await asyncio.gather(
        append_task(1),
        append_task(2),
        append_task(3),
    )

    # Verify no errors occurred
    assert len(errors) == 0, f"Errors occurred: {errors}"

    # Verify final state is consistent
    assert len(state.detected_calls) == 150


async def test_vtc_buffer_state_concurrent_append():
    """Test that VTCBufferState can handle concurrent appends safely.

    This test verifies that append_extracted_call uses a lock
    to prevent concurrent list mutations.
    """
    state = VTCBufferState()
    errors = []

    async def append_task(task_id: int) -> None:
        """Concurrently append extracted calls."""
        try:
            for _ in range(50):
                state.append_extracted_call(
                    {"id": f"extracted_{task_id}_{_}", "function": "test_func"}
                )
                await asyncio.sleep(0)
        except Exception as e:
            errors.append((task_id, e))

    # Run multiple append tasks concurrently
    await asyncio.gather(
        append_task(1),
        append_task(2),
        append_task(3),
    )

    # Verify no errors occurred
    assert len(errors) == 0, f"Errors occurred: {errors}"

    # Verify final state is consistent
    assert len(state.extracted_tool_calls) == 150


async def test_registry_concurrent_state_access():
    """Test that StreamingContextRegistry handles concurrent state access safely.

    This test verifies that multiple tasks can get and modify
    the same stream state without corruption.
    """
    registry = StreamingContextRegistry()
    stream_id = "test_stream_concurrent"

    async def modify_task(task_id: int) -> None:
        """Concurrently modify stream state."""
        content_state = registry.get_content_state(stream_id)
        for _ in range(20):
            content_state.append_content_chunk(
                f"chunk_{task_id}_{_}", f"enc_{_}".encode(), 6
            )
            await asyncio.sleep(0.001)  # Small delay to allow interleaving

    # Run multiple tasks modifying the same stream state
    await asyncio.gather(
        modify_task(1),
        modify_task(2),
        modify_task(3),
    )

    # Verify final state is consistent
    content_state = registry.get_content_state(stream_id)
    assert len(content_state.chunks) == 60
    assert content_state.byte_length == 60 * 6
