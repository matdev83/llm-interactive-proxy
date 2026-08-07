"""
Tests for steering response content accumulation reset.

These tests verify that when a steering replacement response is detected,
the accumulated content is properly cleared to prevent concatenation bugs.
"""

import pytest
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)


class TestSteeringContentReset:
    """Tests for content reset behavior on steering replacement."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(
        self, registry: StreamingContextRegistry
    ) -> ContentAccumulationProcessor:
        """Create a processor with the test registry."""
        return ContentAccumulationProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_steering_replacement_clears_accumulated_content(
        self,
        processor: ContentAccumulationProcessor,
        registry: StreamingContextRegistry,
    ) -> None:
        """Test that _steering_replacement flag clears accumulated content."""
        stream_id = "test-stream-1"

        # First, accumulate some normal content
        chunk1 = StreamingContent(
            content="First chunk of content",
            metadata={"stream_id": stream_id},
            is_done=False,
        )
        await processor.process(chunk1)

        chunk2 = StreamingContent(
            content=" second chunk",
            metadata={"stream_id": stream_id},
            is_done=False,
        )
        await processor.process(chunk2)

        # Verify content was accumulated
        state = registry.get_content_state(stream_id)
        assert len(state.chunks) > 0

        # Now send a steering replacement chunk
        steering_chunk = StreamingContent(
            content="Steering replacement content",
            metadata={
                "stream_id": stream_id,
                "_steering_replacement": True,
            },
            is_done=False,
        )
        await processor.process(steering_chunk)

        # Verify accumulated content was cleared before processing steering chunk
        # The steering chunk should now be the only content
        state = registry.get_content_state(stream_id)
        # After the steering replacement, we should have fresh state
        # (may have one chunk from the steering content itself)
        accumulated = "".join(state.chunks)
        assert "First chunk" not in accumulated
        assert "second chunk" not in accumulated

    @pytest.mark.asyncio
    async def test_steering_replacement_with_final_chunk(
        self,
        processor: ContentAccumulationProcessor,
        registry: StreamingContextRegistry,
    ) -> None:
        """Test steering replacement in final (is_done) chunk."""
        stream_id = "test-stream-2"

        # Accumulate some content
        chunk1 = StreamingContent(
            content="Original content that should be discarded",
            metadata={"stream_id": stream_id},
            is_done=False,
        )
        await processor.process(chunk1)

        # Send final steering replacement
        steering_final = StreamingContent(
            content="Replacement steering message",
            metadata={
                "stream_id": stream_id,
                "_steering_replacement": True,
            },
            is_done=True,
        )
        result = await processor.process(steering_final)

        # The final content should only contain the steering message
        if isinstance(result.content, str):
            assert "Original content" not in result.content
            # Steering message should be present
            assert "Replacement" in result.content or result.content == ""

    @pytest.mark.asyncio
    async def test_normal_accumulation_without_steering_flag(
        self,
        processor: ContentAccumulationProcessor,
        registry: StreamingContextRegistry,
    ) -> None:
        """Test that normal chunks without steering flag accumulate correctly."""
        stream_id = "test-stream-3"

        # Accumulate content normally
        chunks = ["First ", "second ", "third"]
        for text in chunks:
            chunk = StreamingContent(
                content=text,
                metadata={"stream_id": stream_id},
                is_done=False,
            )
            await processor.process(chunk)

        # Verify all content accumulated
        state = registry.get_content_state(stream_id)
        accumulated = "".join(state.chunks)
        for text in chunks:
            assert text in accumulated

    @pytest.mark.asyncio
    async def test_steering_replacement_clears_reasoning_chunks(
        self,
        processor: ContentAccumulationProcessor,
        registry: StreamingContextRegistry,
    ) -> None:
        """Test that reasoning chunks are also cleared on steering replacement."""
        stream_id = "test-stream-4"

        # Accumulate content with reasoning
        chunk1 = StreamingContent(
            content="Content",
            metadata={
                "stream_id": stream_id,
                "reasoning_content": "Some reasoning",
            },
            is_done=False,
        )
        await processor.process(chunk1)

        state = registry.get_content_state(stream_id)
        assert len(state.reasoning_chunks) > 0 or len(state.chunks) > 0

        # Send steering replacement
        steering_chunk = StreamingContent(
            content="Steering",
            metadata={
                "stream_id": stream_id,
                "_steering_replacement": True,
            },
            is_done=False,
        )
        await processor.process(steering_chunk)

        # Verify reasoning was cleared
        state = registry.get_content_state(stream_id)
        # Reasoning should be cleared
        accumulated_reasoning = "".join(state.reasoning_chunks)
        assert "Some reasoning" not in accumulated_reasoning


class TestProcessedResponseSteeringMetadata:
    """Tests for _steering_replacement metadata handling in responses."""

    def test_processed_response_can_carry_steering_flag(self) -> None:
        """Verify ProcessedResponse can carry _steering_replacement metadata."""
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        response = ProcessedResponse(
            content="Steering message",
            metadata={
                "_steering_replacement": True,
                "tool_call_swallowed": True,
            },
        )

        assert response.metadata is not None
        assert response.metadata.get("_steering_replacement") is True
