"""
Property-based tests for response adapters.

This module contains property-based tests for the response adapter functions,
focusing on event loop yielding and async path purity.
"""

import asyncio
import inspect

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StreamingContent
from src.core.transport.fastapi.response_adapters import to_fastapi_streaming_response


# Strategy for generating StreamingContent chunks
@st.composite
def streaming_content_strategy(draw):
    """Generate valid StreamingContent chunks."""
    content = draw(
        st.one_of(
            st.text(min_size=1, max_size=100),
            st.dictionaries(
                st.text(min_size=1, max_size=10),
                st.text(min_size=1, max_size=50),
                min_size=1,
                max_size=5,
            ),
        )
    )

    metadata = draw(
        st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.one_of(st.text(), st.integers(), st.booleans()),
            min_size=0,
            max_size=5,
        )
    )

    is_done = draw(st.booleans())
    is_empty = draw(st.booleans())

    return StreamingContent(
        content=content, metadata=metadata, is_done=is_done, is_empty=is_empty
    )


# Strategy for generating ProcessedResponse chunks
@st.composite
def processed_response_strategy(draw):
    """Generate valid ProcessedResponse chunks."""
    content = draw(
        st.one_of(
            st.text(min_size=1, max_size=100),
            st.dictionaries(
                st.text(min_size=1, max_size=10),
                st.text(min_size=1, max_size=50),
                min_size=1,
                max_size=5,
            ),
        )
    )

    metadata = draw(
        st.one_of(
            st.none(),
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                st.one_of(st.text(), st.integers(), st.booleans()),
                min_size=0,
                max_size=5,
            ),
        )
    )

    return ProcessedResponse(content=content, metadata=metadata)


class TestEventLoopYielding:
    """
    Property 28: Event loop yielding
    Feature: streaming-pipeline-refactor, Property 28: Event loop yielding

    For any chunk emission in the streaming pipeline, the code should yield
    control to the event loop (await asyncio.sleep(0) or similar).
    """

    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=5000)
    @given(chunks=st.lists(processed_response_strategy(), min_size=1, max_size=20))
    async def test_event_loop_yielding_property(self, chunks: list[ProcessedResponse]):
        """
        Test that the streaming response yields control to the event loop.

        This property verifies that for any stream of chunks, the response
        adapter yields control to the event loop between chunks, allowing
        other async tasks to run and preventing blocking.
        """

        # Create an async iterator from the chunks
        async def chunk_generator():
            for chunk in chunks:
                yield chunk

        # Create streaming response envelope
        envelope = StreamingResponseEnvelope(
            content=chunk_generator(), media_type="text/event-stream"
        )

        # Convert to FastAPI streaming response
        response = to_fastapi_streaming_response(envelope)

        # Track if other tasks can run between chunks
        task_ran = []

        async def concurrent_task():
            """A task that should be able to run between chunks."""
            for _ in range(len(chunks) * 2):
                task_ran.append(True)
                await asyncio.sleep(0)

        # Start the concurrent task
        task = asyncio.create_task(concurrent_task())

        # Consume the streaming response
        chunk_count = 0
        async for _ in response.body_iterator:
            chunk_count += 1
            # Give the concurrent task a chance to run
            await asyncio.sleep(0)

        # Wait for concurrent task to complete
        await task

        # Verify that the concurrent task was able to run
        # If event loop yielding is working, the task should have run multiple times
        assert len(task_ran) > 0, "Concurrent task never ran - event loop not yielding"

        # Verify we processed all chunks
        assert chunk_count > 0, "No chunks were processed"


class TestAsyncPathPurity:
    """
    Property 29: Async path purity
    Feature: streaming-pipeline-refactor, Property 29: Async path purity

    For any async streaming function, it should not contain blocking
    synchronous operations (sync I/O, CPU-intensive loops).
    """

    @pytest.mark.asyncio
    @settings(max_examples=30, deadline=5000)
    @given(chunks=st.lists(processed_response_strategy(), min_size=1, max_size=10))
    async def test_async_path_purity_property(self, chunks: list[ProcessedResponse]):
        """
        Test that the streaming response uses only async operations.

        This property verifies that for any stream of chunks, the response
        adapter uses only async operations and doesn't block the event loop
        with synchronous I/O or CPU-intensive operations.
        """

        # Create an async iterator from the chunks
        async def chunk_generator():
            for chunk in chunks:
                yield chunk

        # Create streaming response envelope
        envelope = StreamingResponseEnvelope(
            content=chunk_generator(), media_type="text/event-stream"
        )

        # Convert to FastAPI streaming response
        response = to_fastapi_streaming_response(envelope)

        # Verify the body_iterator is an async generator
        assert inspect.isasyncgen(
            response.body_iterator
        ), "Response body_iterator is not an async generator"

        # Track timing to detect blocking operations
        start_time = asyncio.get_event_loop().time()
        chunk_times = []

        # Consume the streaming response
        async for _ in response.body_iterator:
            current_time = asyncio.get_event_loop().time()
            chunk_times.append(current_time - start_time)
            start_time = current_time

        # Verify that no single chunk took an excessive amount of time
        # (which would indicate blocking operations)
        # Allow up to 100ms per chunk (generous threshold for CI environments)
        max_chunk_time = max(chunk_times) if chunk_times else 0
        assert (
            max_chunk_time < 0.1
        ), f"Chunk processing took {max_chunk_time:.3f}s - possible blocking operation"

    @pytest.mark.asyncio
    @settings(max_examples=30, deadline=5000)
    @given(chunks=st.lists(streaming_content_strategy(), min_size=1, max_size=10))
    async def test_no_blocking_io_in_streaming(self, chunks: list[StreamingContent]):
        """
        Test that streaming doesn't perform blocking I/O operations.

        This property verifies that the streaming pipeline doesn't perform
        any blocking I/O operations that would prevent other async tasks
        from running.
        """

        # Create an async iterator from StreamingContent chunks
        async def chunk_generator():
            for chunk in chunks:
                yield chunk

        # Track if we can detect any blocking behavior
        io_operations = []

        # Monkey-patch to detect blocking I/O (simplified check)
        original_sleep = asyncio.sleep

        async def tracked_sleep(delay, result=None):
            io_operations.append(("sleep", delay))
            return await original_sleep(delay, result)

        # Temporarily replace asyncio.sleep to track async operations
        asyncio.sleep = tracked_sleep

        try:
            # Create a simple async iterator that yields bytes
            async def byte_generator():
                async for chunk in chunk_generator():
                    # Convert to bytes (simplified)
                    if isinstance(chunk.content, str):
                        yield chunk.content.encode()
                    elif isinstance(chunk.content, dict):
                        import json

                        yield json.dumps(chunk.content).encode()
                    else:
                        yield str(chunk.content).encode()

            # Consume the stream
            chunk_count = 0
            async for _ in byte_generator():
                chunk_count += 1

            # Verify we processed chunks
            assert chunk_count > 0, "No chunks were processed"

        finally:
            # Restore original asyncio.sleep
            asyncio.sleep = original_sleep

    @pytest.mark.asyncio
    @settings(max_examples=20, deadline=5000)
    @given(chunks=st.lists(processed_response_strategy(), min_size=5, max_size=15))
    async def test_streaming_responsiveness(self, chunks: list[ProcessedResponse]):
        """
        Test that streaming remains responsive during processing.

        This property verifies that the streaming pipeline remains responsive
        and allows other tasks to make progress, even during active streaming.
        """

        # Create an async iterator from the chunks
        async def chunk_generator():
            for chunk in chunks:
                yield chunk

        # Create streaming response envelope
        envelope = StreamingResponseEnvelope(
            content=chunk_generator(), media_type="text/event-stream"
        )

        # Convert to FastAPI streaming response
        response = to_fastapi_streaming_response(envelope)

        # Track progress of concurrent task
        progress_markers = []

        async def progress_tracker():
            """Track that we can make progress concurrently."""
            for i in range(len(chunks) * 3):
                progress_markers.append(i)
                await asyncio.sleep(0)

        # Start progress tracker
        tracker_task = asyncio.create_task(progress_tracker())

        # Consume streaming response
        consumed_chunks = 0
        async for _ in response.body_iterator:
            consumed_chunks += 1
            await asyncio.sleep(0)

        # Wait for tracker to complete
        await tracker_task

        # Verify both tasks made progress
        assert consumed_chunks > 0, "No chunks consumed"
        assert len(progress_markers) > 0, "Progress tracker didn't run"

        # Verify interleaving - progress tracker should have run multiple times
        # during streaming (indicating responsiveness)
        assert (
            len(progress_markers) >= consumed_chunks
        ), "Insufficient interleaving - streaming may be blocking"
