import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)


@pytest.fixture
def content_accumulation_processor():
    return ContentAccumulationProcessor()


@pytest.mark.asyncio
async def test_content_accumulation_processor_accumulates_multiple_chunks(
    content_accumulation_processor,
):
    # Arrange
    chunk1 = StreamingContent(
        content="Hello, ", metadata={"stream_id": "test-stream-1"}
    )
    chunk2 = StreamingContent(content="world", metadata={"stream_id": "test-stream-1"})
    chunk3 = StreamingContent(content="!", metadata={"stream_id": "test-stream-1"})
    final_chunk = StreamingContent(
        content="", is_done=True, metadata={"stream_id": "test-stream-1"}
    )

    # Act
    processed_chunk1 = await content_accumulation_processor.process(chunk1)
    processed_chunk2 = await content_accumulation_processor.process(chunk2)
    processed_chunk3 = await content_accumulation_processor.process(chunk3)
    processed_final_chunk = await content_accumulation_processor.process(final_chunk)

    # Assert
    assert processed_chunk1.content == ""
    assert processed_chunk2.content == ""
    assert processed_chunk3.content == ""
    assert processed_final_chunk.content == "Hello, world!"
    assert processed_final_chunk.is_done is True


@pytest.mark.asyncio
async def test_content_accumulation_processor_emits_on_is_done(
    content_accumulation_processor,
):
    # Arrange
    chunk1 = StreamingContent(
        content="First part.", metadata={"stream_id": "test-stream-2"}
    )
    final_chunk = StreamingContent(
        content="Second part.", is_done=True, metadata={"stream_id": "test-stream-2"}
    )

    # Act
    processed_chunk1 = await content_accumulation_processor.process(chunk1)
    processed_final_chunk = await content_accumulation_processor.process(final_chunk)

    # Assert
    assert processed_chunk1.content == ""
    assert processed_final_chunk.content == "First part.Second part."
    assert processed_final_chunk.is_done is True


@pytest.mark.asyncio
async def test_content_accumulation_processor_handles_empty_chunks(
    content_accumulation_processor,
):
    # Arrange
    chunk1 = StreamingContent(
        content="Some content", metadata={"stream_id": "test-stream-3"}
    )
    empty_chunk = StreamingContent(content="", metadata={"stream_id": "test-stream-3"})
    final_empty_chunk = StreamingContent(
        content="", is_done=True, metadata={"stream_id": "test-stream-3"}
    )

    # Act
    processed_chunk1 = await content_accumulation_processor.process(chunk1)
    processed_empty_chunk = await content_accumulation_processor.process(empty_chunk)
    processed_final_empty_chunk = await content_accumulation_processor.process(
        final_empty_chunk
    )

    # Assert
    assert processed_chunk1.content == ""
    assert processed_empty_chunk.content == ""
    assert processed_final_empty_chunk.content == "Some content"
    assert processed_final_empty_chunk.is_done is True


@pytest.mark.asyncio
async def test_content_accumulation_processor_preserves_metadata_for_empty_chunks(
    content_accumulation_processor,
):
    chunk = StreamingContent(content="", metadata={"id": "chunk-1"})

    processed_chunk = await content_accumulation_processor.process(chunk)

    assert processed_chunk.metadata == {"id": "chunk-1"}
    assert processed_chunk.content == ""
    assert processed_chunk.is_done is False


@pytest.mark.asyncio
async def test_content_accumulation_processor_resets_buffer_after_emission(
    content_accumulation_processor,
):
    # Arrange
    chunk1 = StreamingContent(
        content="First stream part. ",
        is_done=True,
        metadata={"stream_id": "test-stream-4"},
    )
    chunk2 = StreamingContent(
        content="Second stream part.", metadata={"stream_id": "test-stream-5"}
    )
    final_chunk_2 = StreamingContent(
        content="", is_done=True, metadata={"stream_id": "test-stream-5"}
    )

    # Act - first stream
    processed_chunk1 = await content_accumulation_processor.process(chunk1)
    # Act - second stream
    processed_chunk2 = await content_accumulation_processor.process(chunk2)
    processed_final_chunk_2 = await content_accumulation_processor.process(
        final_chunk_2
    )

    # Assert first stream
    assert processed_chunk1.content == "First stream part. "
    assert processed_chunk1.is_done is True

    # Assert second stream starts clean
    assert processed_chunk2.content == ""
    assert processed_final_chunk_2.content == "Second stream part."
    assert processed_final_chunk_2.is_done is True


@pytest.mark.asyncio
async def test_content_accumulation_processor_empty_initial_stream(
    content_accumulation_processor,
):
    # Arrange
    final_chunk = StreamingContent(content="", is_done=True)

    # Act
    processed_final_chunk = await content_accumulation_processor.process(final_chunk)

    # Assert
    assert processed_final_chunk.content == ""
    assert processed_final_chunk.is_done is True


@pytest.mark.asyncio
async def test_content_accumulation_processor_reset_method_clears_buffer(
    content_accumulation_processor,
):
    chunk = StreamingContent(content="stale")
    await content_accumulation_processor.process(chunk)

    content_accumulation_processor.reset()

    final_chunk = StreamingContent(content="fresh", is_done=True)
    processed_final_chunk = await content_accumulation_processor.process(final_chunk)

    assert processed_final_chunk.content == "fresh"
    assert processed_final_chunk.is_done is True


@pytest.mark.asyncio
async def test_accumulated_reasoning_metadata_is_preserved(
    content_accumulation_processor,
) -> None:
    """Ensure reasoning fragments are preserved alongside accumulated content."""

    first_chunk = StreamingContent(
        content="Step 1.",
        metadata={
            "stream_id": "reasoning-stream",
            "reasoning_content": "Thinking about step 1.",
        },
    )
    final_chunk = StreamingContent(
        content="Step 2.",
        metadata={
            "stream_id": "reasoning-stream",
            "reasoning_content": "Considering next move.",
        },
        is_done=True,
    )

    await content_accumulation_processor.process(first_chunk)
    result = await content_accumulation_processor.process(final_chunk)

    assert result.metadata.get("accumulated_content") == "Step 1.Step 2."
    assert (
        result.metadata.get("accumulated_reasoning")
        == "Thinking about step 1.Considering next move."
    )


@pytest.mark.asyncio
async def test_openai_format_chunks_pass_through_unchanged(
    content_accumulation_processor,
) -> None:
    """OpenAI-format chunks with choices should pass through unchanged for SSE output.

    This is a regression test for a bug where OpenAI-format chunks were being
    JSON-stringified and accumulated, breaking the streaming output.
    """
    # Simulate an OpenAI-format content chunk
    content_chunk = {
        "id": "chatcmpl-test-123",
        "object": "chat.completion.chunk",
        "created": 1699000000,
        "model": "gemini-2.5-pro",
        "choices": [
            {
                "index": 0,
                "delta": {"content": "Hello, world!"},
                "finish_reason": None,
            }
        ],
    }

    chunk = StreamingContent(
        content=content_chunk,
        metadata={"stream_id": "openai-format-stream"},
    )

    result = await content_accumulation_processor.process(chunk)

    # The original dict should be preserved for SSE output
    assert isinstance(result.content, dict)
    assert result.content["id"] == "chatcmpl-test-123"
    assert result.content["choices"][0]["delta"]["content"] == "Hello, world!"


@pytest.mark.asyncio
async def test_openai_format_usage_chunks_pass_through(
    content_accumulation_processor,
) -> None:
    """Usage-only chunks with empty choices should pass through unchanged.

    These chunks should NOT contribute to accumulated content.
    """
    usage_chunk = {
        "id": "chatcmpl-usage-456",
        "object": "chat.completion.chunk",
        "created": 1699000000,
        "model": "gemini-2.5-pro",
        "choices": [],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }

    chunk = StreamingContent(
        content=usage_chunk,
        metadata={"stream_id": "usage-stream"},
    )

    result = await content_accumulation_processor.process(chunk)

    # Usage chunk should pass through unchanged
    assert isinstance(result.content, dict)
    assert result.content["choices"] == []
    assert result.content["usage"]["total_tokens"] == 150


@pytest.mark.asyncio
async def test_openai_format_chunks_accumulate_content_in_metadata(
    content_accumulation_processor,
) -> None:
    """OpenAI-format chunks should accumulate text content for metadata.

    When is_done=True, accumulated_content should contain the extracted text.
    """
    chunk1 = StreamingContent(
        content={
            "id": "chatcmpl-1",
            "choices": [{"delta": {"content": "Hello, "}}],
        },
        metadata={"stream_id": "accum-stream"},
    )
    chunk2 = StreamingContent(
        content={
            "id": "chatcmpl-2",
            "choices": [{"delta": {"content": "world!"}}],
        },
        metadata={"stream_id": "accum-stream"},
    )
    final_chunk = StreamingContent(
        content={
            "id": "chatcmpl-final",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
        },
        metadata={"stream_id": "accum-stream"},
        is_done=True,
    )

    await content_accumulation_processor.process(chunk1)
    await content_accumulation_processor.process(chunk2)
    result = await content_accumulation_processor.process(final_chunk)

    # Accumulated content should be in metadata
    assert result.metadata.get("accumulated_content") == "Hello, world!"
    # Original dict should still be preserved
    assert isinstance(result.content, dict)
    assert result.content["id"] == "chatcmpl-final"
