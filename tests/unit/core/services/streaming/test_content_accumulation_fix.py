import pytest
from src.core.ports.streaming_contracts import StopChunkWithUsage, StreamingContent
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)


@pytest.mark.asyncio
async def test_accumulate_sse_strings_then_stop_chunk():
    processor = ContentAccumulationProcessor()
    stream_id = "test-stream-1"

    # Simulate SSE chunks as strings (which ContentAccumulationProcessor buffers)
    chunks = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n',
        'data: {"choices": [{"delta": {"content": " World"}}]}\n\n',
    ]

    for chunk in chunks:
        content = StreamingContent(
            content=chunk,
            is_done=False,
            metadata={"model": "test", "stream_id": stream_id},
            usage=None,
            raw_data=chunk.encode(),
        )
        result = await processor.process(content)
        # Should return empty content while accumulating
        assert result.content == ""
        assert not result.is_done

    # Now send StopChunkWithUsage
    stop_chunk = StopChunkWithUsage(
        {
            "choices": [{"finish_reason": "stop", "delta": {"role": "assistant"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )

    content = StreamingContent(
        content=stop_chunk,
        is_done=True,
        metadata={"model": "test", "stream_id": stream_id},
        usage=None,
        raw_data=b"",
    )

    result = await processor.process(content)

    # Verify result is the StopChunkWithUsage
    assert isinstance(result.content, StopChunkWithUsage)

    # Verify content was merged
    choices = result.content.get("choices")
    assert choices
    delta = choices[0].get("delta")
    assert delta

    expected_content = "".join(chunks)
    assert delta.get("content") == expected_content


@pytest.mark.asyncio
async def test_accumulate_text_then_stop_chunk():
    processor = ContentAccumulationProcessor()
    stream_id = "test-stream-2"

    # Simulate text chunks (e.g. from a decoded stream)
    chunks = ["Hello", " World"]

    for chunk in chunks:
        content = StreamingContent(
            content=chunk,
            is_done=False,
            metadata={"model": "test", "stream_id": stream_id},
            usage=None,
            raw_data=chunk.encode(),
        )
        result = await processor.process(content)
        assert result.content == ""

    # StopChunkWithUsage
    stop_chunk = StopChunkWithUsage(
        {
            "choices": [{"finish_reason": "stop", "delta": {"role": "assistant"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )

    content = StreamingContent(
        content=stop_chunk,
        is_done=True,
        metadata={"model": "test", "stream_id": stream_id},
        usage=None,
        raw_data=b"",
    )

    result = await processor.process(content)

    assert isinstance(result.content, StopChunkWithUsage)
    assert result.content["choices"][0]["delta"]["content"] == "Hello World"
