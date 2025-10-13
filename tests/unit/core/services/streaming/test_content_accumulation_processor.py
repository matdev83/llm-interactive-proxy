import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from src.core.domain.streaming_response_processor import StreamingContent
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
