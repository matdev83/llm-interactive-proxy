"""Repro script for ResponseCaptureProcessor race condition."""

import asyncio

from src.core.domain.streaming_response_processor import StreamingContent
from src.core.memory.response_capture_processor import ResponseCaptureProcessor


class MockMemoryCapture:
    """Mock memory capture middleware."""

    async def capture_response(self, session_id: str, **kwargs):
        await asyncio.sleep(0.01)


async def test_concurrent_append():
    """Test concurrent appends to content_buffer."""
    processor = ResponseCaptureProcessor(MockMemoryCapture(), "test-session")

    async def append_content(chunk_id: int):
        for i in range(100):
            content = StreamingContent(
                content=f"chunk-{chunk_id}-{i}",
                is_done=False,
                metadata={}
            )
            await processor.process(content)

    # Create concurrent tasks that modify the same processor
    tasks = [append_content(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # Check if all content was captured (should be 1000 chunks)
    actual = len(processor._content_buffer)
    expected = 1000
    print(f"Expected {expected} chunks, got {actual}")

    if actual != expected:
        print("RACE CONDITION DETECTED: Content buffer has wrong size!")
        return False

    print("No race condition detected in this run")
    return True


async def test_concurrent_tool_calls():
    """Test concurrent tool call extends."""
    processor = ResponseCaptureProcessor(MockMemoryCapture(), "test-session")

    async def append_tool_calls(task_id: int):
        for i in range(100):
            content = StreamingContent(
                content="",
                is_done=False,
                metadata={
                    "tool_calls": [{"id": f"call-{task_id}-{i}", "function": {"name": "test"}}]
                }
            )
            await processor.process(content)

    tasks = [append_tool_calls(i) for i in range(10)]
    await asyncio.gather(*tasks)

    actual = len(processor._tool_calls)
    expected = 1000
    print(f"Expected {expected} tool calls, got {actual}")

    if actual != expected:
        print("RACE CONDITION DETECTED: Tool calls buffer has wrong size!")
        return False

    print("No race condition detected in this run")
    return True


async def main():
    print("=" * 60)
    print("Testing ResponseCaptureProcessor race conditions...")
    print("=" * 60)

    print("\nTest 1: Concurrent content appends")
    result1 = await test_concurrent_append()

    print("\nTest 2: Concurrent tool call extends")
    result2 = await test_concurrent_tool_calls()

    if not result1 or not result2:
        print("\n" + "=" * 60)
        print("RACE CONDITION CONFIRMED!")
        print("=" * 60)
        return 1

    print("\n" + "=" * 60)
    print("No race conditions detected (may need multiple runs)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
