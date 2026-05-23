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


@pytest.mark.asyncio
async def test_openai_stream_done_marker_does_not_reemit_accumulated_content():
    """Regression: OpenAI-style streams may end with an SSE [DONE] marker chunk.

    When earlier chunks were forwarded as OpenAI deltas, ContentAccumulationProcessor
    must not re-emit the full accumulated content on the terminal marker, otherwise
    clients will see the assistant message duplicated.
    """
    processor = ContentAccumulationProcessor()
    stream_id = "test-openai-stream"

    # Simulate OpenAI-style parsed chunks: content is already extracted as text,
    # and raw_data preserves the OpenAI dict with "choices" for openai detection.
    openai_raw = {"choices": [{"delta": {"content": "Hello"}}], "id": "x"}
    first = StreamingContent(
        content="Hello",
        is_done=False,
        metadata={"stream_id": stream_id, "model": "test"},
        raw_data=openai_raw,
    )
    first_out = await processor.process(first)
    assert isinstance(first_out.content, dict)

    # Simulate SSEBytesParser output for "data: [DONE]\n\n" (is_done=True, no OpenAI dict payload).
    done_marker = StreamingContent(
        content="",
        is_done=True,
        metadata={"stream_id": stream_id, "model": "test"},
        raw_data=b"data: [DONE]\n\n",
    )

    done_out = await processor.process(done_marker)
    assert done_out.is_done is True
    assert done_out.metadata.get("accumulated_content") == "Hello"
    assert done_out.content == ""
