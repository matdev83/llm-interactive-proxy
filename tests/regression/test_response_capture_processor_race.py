"""Regression test for ResponseCaptureProcessor race condition."""

import asyncio

from src.core.domain.streaming_response_processor import StreamingContent
from src.core.memory.response_capture_processor import ResponseCaptureProcessor


class MockMemoryCapture:
    """Mock memory capture middleware."""

    def __init__(self):
        self.captured = []

    async def capture_response(self, session_id: str, **kwargs):
        await asyncio.sleep(0.001)
        self.captured.append({"session_id": session_id, "kwargs": kwargs})


async def test_concurrent_content_append_is_thread_safe():
    """Test that concurrent appends to content_buffer are thread-safe."""
    processor = ResponseCaptureProcessor(MockMemoryCapture(), "test-session")

    async def append_content(chunk_id: int):
        for i in range(50):
            content = StreamingContent(
                content=f"chunk-{chunk_id}-{i}", is_done=False, metadata={}
            )
            await processor.process(content)

    # Create concurrent tasks that modify same processor
    tasks = [append_content(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # All content should be captured
    actual = len(processor._content_buffer)
    expected = 500  # 10 tasks * 50 iterations each

    # With lock protection, we should get expected count
    # Without lock, we might see corruption or missing elements
    assert actual == expected, f"Expected {expected} chunks, got {actual}"


async def test_concurrent_tool_calls_extend_is_thread_safe():
    """Test that concurrent extends to tool_calls are thread-safe."""
    processor = ResponseCaptureProcessor(MockMemoryCapture(), "test-session")

    async def append_tool_calls(task_id: int):
        for i in range(50):
            content = StreamingContent(
                content="",
                is_done=False,
                metadata={
                    "tool_calls": [
                        {"id": f"call-{task_id}-{i}", "function": {"name": "test"}}
                    ]
                },
            )
            await processor.process(content)

    tasks = [append_tool_calls(i) for i in range(10)]
    await asyncio.gather(*tasks)

    actual = len(processor._tool_calls)
    expected = 500

    assert actual == expected, f"Expected {expected} tool calls, got {actual}"


async def test_concurrent_mixed_operations_is_thread_safe():
    """Test that concurrent mixed operations (content + tool_calls) are thread-safe."""
    processor = ResponseCaptureProcessor(MockMemoryCapture(), "test-session")

    async def append_content_only(chunk_id: int):
        for i in range(30):
            content = StreamingContent(
                content=f"content-{chunk_id}-{i}", is_done=False, metadata={}
            )
            await processor.process(content)

    async def append_tool_calls_only(task_id: int):
        for i in range(30):
            content = StreamingContent(
                content="",
                is_done=False,
                metadata={
                    "tool_calls": [
                        {"id": f"call-{task_id}-{i}", "function": {"name": "tool"}}
                    ]
                },
            )
            await processor.process(content)

    # Mix of tasks modifying different buffers
    tasks = [append_content_only(i) for i in range(5)] + [
        append_tool_calls_only(i) for i in range(5)
    ]
    await asyncio.gather(*tasks)

    # Check both buffers
    assert (
        len(processor._content_buffer) == 150
    ), f"Expected 150 content chunks, got {len(processor._content_buffer)}"
    assert (
        len(processor._tool_calls) == 150
    ), f"Expected 150 tool calls, got {len(processor._tool_calls)}"


async def test_reset_during_concurrent_operations():
    """Test that reset() doesn't cause issues with concurrent operations."""
    processor = ResponseCaptureProcessor(MockMemoryCapture(), "test-session")

    async def append_content():
        for i in range(100):
            content = StreamingContent(content=f"chunk-{i}", is_done=False, metadata={})
            await processor.process(content)

    async def reset_periodically():
        for _ in range(5):
            await asyncio.sleep(0.01)
            processor.reset()

    # Run appends and resets concurrently
    task1 = asyncio.create_task(append_content())
    task2 = asyncio.create_task(reset_periodically())

    await asyncio.gather(task1, task2)

    # Should complete without errors
    assert True  # If we got here without exception, test passes


if __name__ == "__main__":
    asyncio.run(test_concurrent_content_append_is_thread_safe())
    asyncio.run(test_concurrent_tool_calls_extend_is_thread_safe())
    asyncio.run(test_concurrent_mixed_operations_is_thread_safe())
    asyncio.run(test_reset_during_concurrent_operations())
    print("All tests passed!")
