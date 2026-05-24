"""
Property-based tests for streaming processors.

These tests verify universal properties that should hold across all
streaming processor implementations.
"""

from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.ports.streaming_contracts import StreamingContent
from src.core.ports.streaming_processors import (
    LoopDetectionProcessor,
    ThinkTagsProcessor,
)


# Strategies for generating test data
@st.composite
def streaming_content_strategy(draw):
    """Generate arbitrary StreamingContent for testing."""
    content_type = draw(st.sampled_from(["str", "dict", "bytes"]))

    if content_type == "str":
        content = draw(st.text(min_size=0, max_size=200))
    elif content_type == "dict":
        content = draw(
            st.dictionaries(
                st.text(min_size=1, max_size=10),
                st.text(min_size=0, max_size=50),
                min_size=0,
                max_size=5,
            )
        )
    else:  # bytes
        content = draw(st.binary(min_size=0, max_size=200))

    metadata = draw(
        st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.one_of(
                st.text(min_size=0, max_size=50),
                st.integers(),
                st.booleans(),
                st.none(),
            ),
            min_size=0,
            max_size=10,
        )
    )

    is_done = draw(st.booleans())
    is_empty = draw(st.booleans())
    stream_id = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))

    return StreamingContent(
        content=content,
        metadata=metadata,
        is_done=is_done,
        is_empty=is_empty,
        stream_id=stream_id,
    )


@st.composite
def non_done_streaming_content_strategy(draw):
    """Generate StreamingContent that is not a done marker."""
    chunk = draw(streaming_content_strategy())
    # Ensure it's not a done marker
    chunk.is_done = False
    return chunk


class TestMiddlewareIdempotence:
    """
    Property 9: Middleware idempotence
    Feature: streaming-pipeline-refactor, Property 9: Middleware idempotence

    For any middleware transformation, applying it twice to the same
    StreamingContent should produce the same result as applying it once.

    Validates: Requirements 3.3
    """

    @pytest.mark.asyncio
    @given(chunk=non_done_streaming_content_strategy())
    @settings(max_examples=10, deadline=None)  # Reduced from 20 for performance
    async def test_loop_detection_processor_idempotence(self, chunk):
        """Loop detection processor should be idempotent."""
        processor = LoopDetectionProcessor()

        # Apply processor once
        result1 = await processor.process(chunk)

        # Apply processor again to the result
        result2 = await processor.process(result1)

        # Results should be identical
        assert result1.content == result2.content
        assert result1.metadata == result2.metadata
        assert result1.is_done == result2.is_done
        assert result1.is_empty == result2.is_empty
        assert result1.stream_id == result2.stream_id

    @pytest.mark.asyncio
    @given(chunk=non_done_streaming_content_strategy())
    @settings(max_examples=20, deadline=None)
    async def test_think_tags_processor_idempotence(self, chunk):
        """Think tags processor should be idempotent."""
        processor = ThinkTagsProcessor(enabled=True)

        # Apply processor once
        result1 = await processor.process(chunk)

        # Apply processor again to the result
        result2 = await processor.process(result1)

        # Results should be identical
        assert result1.content == result2.content
        assert result1.metadata == result2.metadata
        assert result1.is_done == result2.is_done
        assert result1.is_empty == result2.is_empty
        assert result1.stream_id == result2.stream_id

    @pytest.mark.asyncio
    @given(chunk=streaming_content_strategy())
    @settings(max_examples=20, deadline=None)
    async def test_done_marker_passthrough_idempotence(self, chunk):
        """Done markers should pass through unchanged (idempotent)."""
        # Force chunk to be a done marker
        chunk.is_done = True

        processors = [
            LoopDetectionProcessor(),
            ThinkTagsProcessor(enabled=True),
        ]

        for processor in processors:
            result = await processor.process(chunk)

            # Done marker should pass through unchanged
            assert result.is_done is True
            assert result.content == chunk.content
            assert result.metadata == chunk.metadata


class TestLoopDetectionModalityIsolation:
    """Ensure content loop detection skips tool-call payloads."""

    class _FailingDetector:
        def __init__(self) -> None:
            self.calls = 0

        def process_chunk(self, chunk: str):
            self.calls += 1
            raise AssertionError("Detector should not run for tool-call chunks")

        def reset(self) -> None:  # pragma: no cover - simple stub
            return None

    @pytest.mark.asyncio
    async def test_loop_detection_processor_skips_tool_call_chunks(self) -> None:
        processor = LoopDetectionProcessor()
        processor._detector = cast(Any, self._FailingDetector())  # type: ignore[attr-defined]
        chunk = StreamingContent(
            content="repeat repeat",
            metadata={
                "tool_calls": [
                    {"function": {"name": "execute_command", "arguments": "{}"}}
                ]
            },
            is_done=False,
            is_empty=False,
        )

        result = await processor.process(chunk)
        assert "loop_detected" not in result.metadata


class TestReasoningIsolation:
    """
    Property 18: Reasoning isolation
    Feature: streaming-pipeline-refactor, Property 18: Reasoning isolation

    For any middleware transformation, reasoning_content in metadata
    should never be moved into the main content field.

    Validates: Requirements 7.2
    """

    @pytest.mark.asyncio
    @given(
        reasoning_text=st.text(min_size=1, max_size=200),
        main_content=st.text(min_size=0, max_size=200),
    )
    @settings(max_examples=20, deadline=None)
    async def test_reasoning_stays_in_metadata(self, reasoning_text, main_content):
        """Reasoning content should never leak into main content."""
        # Create chunk with reasoning in metadata
        chunk = StreamingContent(
            content=main_content,
            metadata={"reasoning_content": reasoning_text},
            is_done=False,
            is_empty=False,
        )

        processors = [
            LoopDetectionProcessor(),
            ThinkTagsProcessor(enabled=True),
        ]

        for processor in processors:
            result = await processor.process(chunk)

            # Reasoning should stay in metadata
            if (
                "reasoning_content" in result.metadata
                and isinstance(result.content, str)
                and reasoning_text not in main_content
            ):
                # The reasoning text should not appear in the main content
                # (unless it was already there in the original)
                assert reasoning_text not in result.content

    @pytest.mark.asyncio
    @given(
        think_content=st.text(min_size=1, max_size=100),
        response_content=st.text(min_size=0, max_size=100),
    )
    @settings(max_examples=20, deadline=None)
    async def test_think_tags_processor_extracts_to_metadata(
        self, think_content, response_content
    ):
        """Think tags processor should extract reasoning to metadata, not main content."""
        # Create content with think tags
        content_with_tags = f"<think>{think_content}</think>{response_content}"

        chunk = StreamingContent(
            content=content_with_tags,
            metadata={},
            is_done=False,
            is_empty=False,
            stream_id="test-session",
        )

        processor = ThinkTagsProcessor(enabled=True)
        result = await processor.process(chunk)

        # If reasoning was extracted, it should be in metadata
        if "reasoning_content" in result.metadata:
            reasoning = result.metadata["reasoning_content"]
            # The extracted reasoning should not be in the main content
            if isinstance(result.content, str) and reasoning:
                assert reasoning not in result.content or reasoning in response_content


class TestDoneMarkerPassthrough:
    """
    Property 19: Done marker passthrough
    Feature: streaming-pipeline-refactor, Property 19: Done marker passthrough

    For any middleware processor in a chain, when it receives a chunk
    with is_done=True, it should yield a chunk with is_done=True.

    Validates: Requirements 7.3
    """

    @pytest.mark.asyncio
    @given(chunk=streaming_content_strategy())
    @settings(max_examples=20, deadline=None)
    async def test_loop_detection_passes_done_marker(self, chunk):
        """Loop detection processor should pass through done markers."""
        # Force chunk to be a done marker
        chunk.is_done = True

        processor = LoopDetectionProcessor()
        result = await processor.process(chunk)

        # Done marker should pass through
        assert result.is_done is True

    @pytest.mark.asyncio
    @given(chunk=streaming_content_strategy())
    @settings(max_examples=20, deadline=None)
    async def test_think_tags_passes_done_marker(self, chunk):
        """Think tags processor should pass through done markers."""
        # Force chunk to be a done marker
        chunk.is_done = True

        processor = ThinkTagsProcessor(enabled=True)
        result = await processor.process(chunk)

        # Done marker should pass through
        assert result.is_done is True

    @pytest.mark.asyncio
    @given(chunk=streaming_content_strategy())
    @settings(max_examples=20, deadline=None)
    async def test_processor_chain_preserves_done_marker(self, chunk):
        """A chain of processors should preserve done markers."""
        # Force chunk to be a done marker
        chunk.is_done = True

        # Create processor chain
        processors = [
            LoopDetectionProcessor(),
            ThinkTagsProcessor(enabled=True),
        ]

        # Process through chain
        result = chunk
        for processor in processors:
            result = await processor.process(result)

        # Done marker should still be set
        assert result.is_done is True


class TestStreamStateIsolation:
    """
    Property 21: Stream state isolation
    Feature: streaming-pipeline-refactor, Property 21: Stream state isolation

    For any two concurrent streams, middleware state for one stream
    should not affect the other stream's processing.

    Validates: Requirements 7.5, 9.2
    """

    @pytest.mark.asyncio
    @given(
        content1=st.text(min_size=1, max_size=100),
        content2=st.text(min_size=1, max_size=100),
        stream_id1=st.text(min_size=1, max_size=50),
        stream_id2=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=20, deadline=None)
    async def test_loop_detection_isolates_streams(
        self, content1, content2, stream_id1, stream_id2
    ):
        """Loop detection should isolate state between different streams."""
        # Ensure different stream IDs
        if stream_id1 == stream_id2:
            stream_id2 = stream_id2 + "_different"

        processor = LoopDetectionProcessor()

        # Create chunks for two different streams
        chunk1 = StreamingContent(
            content=content1,
            metadata={},
            is_done=False,
            is_empty=False,
            stream_id=stream_id1,
        )

        chunk2 = StreamingContent(
            content=content2,
            metadata={},
            is_done=False,
            is_empty=False,
            stream_id=stream_id2,
        )

        # Process chunks from both streams
        result1 = await processor.process(chunk1)
        result2 = await processor.process(chunk2)

        # Both should process successfully without interference
        assert result1.stream_id == stream_id1
        assert result2.stream_id == stream_id2

        # Processing stream 2 should not affect stream 1's state
        # (we can verify this by processing more chunks from stream 1)
        chunk1_again = StreamingContent(
            content=content1,
            metadata={},
            is_done=False,
            is_empty=False,
            stream_id=stream_id1,
        )
        result1_again = await processor.process(chunk1_again)
        assert result1_again.stream_id == stream_id1

    @pytest.mark.asyncio
    @given(
        content1=st.text(min_size=1, max_size=100),
        content2=st.text(min_size=1, max_size=100),
        stream_id1=st.text(min_size=1, max_size=50),
        stream_id2=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=20, deadline=None)
    async def test_think_tags_isolates_streams(
        self, content1, content2, stream_id1, stream_id2
    ):
        """Think tags processor should isolate state between different streams."""
        # Ensure different stream IDs
        if stream_id1 == stream_id2:
            stream_id2 = stream_id2 + "_different"

        processor = ThinkTagsProcessor(enabled=True)

        # Create chunks for two different streams
        chunk1 = StreamingContent(
            content=f"<think>{content1}",  # Incomplete think tag
            metadata={},
            is_done=False,
            is_empty=False,
            stream_id=stream_id1,
        )

        chunk2 = StreamingContent(
            content=content2,
            metadata={},
            is_done=False,
            is_empty=False,
            stream_id=stream_id2,
        )

        # Process chunks from both streams
        result1 = await processor.process(chunk1)
        result2 = await processor.process(chunk2)

        # Both should process successfully without interference
        assert result1.stream_id == stream_id1
        assert result2.stream_id == stream_id2

        # Stream 2 should not be affected by stream 1's buffering state
        assert result2.content == content2

    @pytest.mark.asyncio
    @given(
        stream_id1=st.text(min_size=1, max_size=50),
        stream_id2=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=20, deadline=None)
    async def test_reset_clears_state_for_new_stream(self, stream_id1, stream_id2):
        """Reset should clear state without affecting other streams."""
        # Ensure different stream IDs
        if stream_id1 == stream_id2:
            stream_id2 = stream_id2 + "_different"

        processor = ThinkTagsProcessor(enabled=True)

        # Process chunk from stream 1
        chunk1 = StreamingContent(
            content="<think>reasoning",
            metadata={},
            is_done=False,
            is_empty=False,
            stream_id=stream_id1,
        )
        await processor.process(chunk1)

        # Reset processor
        processor.reset()

        # Process chunk from stream 2 - should work normally
        chunk2 = StreamingContent(
            content="normal content",
            metadata={},
            is_done=False,
            is_empty=False,
            stream_id=stream_id2,
        )
        result2 = await processor.process(chunk2)

        # Should process normally without any state from stream 1
        assert result2.content == "normal content"
        assert result2.stream_id == stream_id2
