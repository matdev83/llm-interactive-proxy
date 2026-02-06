"""
Unit tests for SSE Assembler.

This module contains unit tests that verify specific behaviors
of the SSE assembler implementation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import (
    SentinelManager,
    StopChunkWithUsage,
    StreamingContent,
)
from src.core.ports.streaming_metrics import get_sampler_instance, reset_sampler


# Helper function to create async iterator from list
async def async_iter(items: list[StreamingContent]) -> AsyncIterator[StreamingContent]:
    """Convert a list to an async iterator."""
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_basic_sse_assembly() -> None:
    """Test basic SSE assembly with simple chunks."""
    # Arrange
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(
            content="Hello",
            metadata={"provider": "openai", "role": "assistant"},
        ),
        StreamingContent(
            content=" world",
            metadata={"provider": "openai"},
        ),
        SentinelManager.create_done_chunk(),
    ]
    stream = async_iter(chunks)

    # Act
    result = []
    async for chunk_bytes in assembler.assemble_stream(stream):
        result.append(chunk_bytes)

    # Assert
    assert len(result) == 4
    assert result[0].startswith(b"data: ")
    assert result[0].endswith(b"\n\n")
    assert result[1].startswith(b"data: ")
    assert result[1].endswith(b"\n\n")
    assert b'"finish_reason": "stop"' in result[2]
    assert result[3] == b"data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_sse_assembly_with_metadata() -> None:
    """Test SSE assembly preserves metadata in chunks."""
    # Arrange
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(
            content="Test",
            metadata={
                "provider": "openai",
                "model": "gpt-4",
                "role": "assistant",
                "id": "chatcmpl-123",
            },
        ),
        SentinelManager.create_done_chunk(),
    ]
    stream = async_iter(chunks)

    # Act
    result = []
    async for chunk_bytes in assembler.assemble_stream(stream):
        result.append(chunk_bytes)

    # Assert
    assert len(result) == 3
    # Verify the chunk contains the metadata
    chunk_str = result[0].decode("utf-8")
    assert "data: " in chunk_str
    assert '"model": "gpt-4"' in chunk_str
    assert '"id": "chatcmpl-123"' in chunk_str
    assert '"model": "gpt-4"' in chunk_str
    assert '"id": "chatcmpl-123"' in chunk_str
    terminal_str = result[1].decode("utf-8")
    assert '"finish_reason": "stop"' in terminal_str
    assert '"model": "gpt-4"' in terminal_str
    assert '"id": "chatcmpl-123"' in terminal_str


@pytest.mark.asyncio
async def test_sse_assembly_skips_empty_chunks() -> None:
    """Test that empty chunks are skipped unless they're done markers."""
    # Arrange
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(content="Hello", metadata={"provider": "openai"}),
        StreamingContent(content="", metadata={"provider": "openai"}, is_empty=True),
        StreamingContent(content=" world", metadata={"provider": "openai"}),
        SentinelManager.create_done_chunk(),
    ]
    stream = async_iter(chunks)

    # Act
    result = []
    async for chunk_bytes in assembler.assemble_stream(stream):
        result.append(chunk_bytes)

    # Assert
    # Should have 3 chunks: "Hello", " world", and [DONE]
    # The empty chunk should be skipped
    assert len(result) == 4
    assert b'"finish_reason": "stop"' in result[2]
    assert result[3] == b"data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_sse_preserves_whitespace_only_chunks() -> None:
    """Whitespace-only deltas should not be dropped, even if marked empty."""
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(content="publishing", metadata={"provider": "openai"}),
        StreamingContent(content=" ", metadata={"provider": "openai"}, is_empty=True),
        StreamingContent(content="5", metadata={"provider": "openai"}),
        SentinelManager.create_done_chunk(),
    ]
    stream = async_iter(chunks)

    result: list[bytes] = []
    async for chunk_bytes in assembler.assemble_stream(stream):
        result.append(chunk_bytes)

    combined = b"".join(result).decode("utf-8")
    assert '"content": " "' in combined


@pytest.mark.asyncio
async def test_tool_calls_strip_extra_content() -> None:
    """extra_content should be removed before emitting to clients."""
    assembler = SSEAssembler()
    tc = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "Read", "arguments": "{}"},
        "extra_content": {"google": {"thought_signature": "secret"}},
    }
    chunks = [
        StreamingContent(
            content="",
            metadata={"provider": "openai", "tool_calls": [tc]},
        ),
        SentinelManager.create_done_chunk(),
    ]
    stream = async_iter(chunks)

    rendered = b"".join([chunk async for chunk in assembler.assemble_stream(stream)])
    rendered_text = rendered.decode("utf-8")
    assert "extra_content" not in rendered_text
    assert '"tool_calls":' in rendered_text


@pytest.mark.asyncio
async def test_sse_assembly_with_tool_calls() -> None:
    """Test SSE assembly with tool calls in metadata."""
    # Arrange
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(
            content="",
            metadata={
                "provider": "openai",
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": "{}"},
                    }
                ],
            },
        ),
        SentinelManager.create_done_chunk(),
    ]
    stream = async_iter(chunks)

    # Act
    result = []
    async for chunk_bytes in assembler.assemble_stream(stream):
        result.append(chunk_bytes)

    # Assert
    assert len(result) == 3
    chunk_str = result[0].decode("utf-8")
    assert "tool_calls" in chunk_str
    assert "get_weather" in chunk_str
    assert b'"finish_reason": "tool_calls"' in result[1]


@pytest.mark.asyncio
async def test_sse_assembly_with_reasoning_content() -> None:
    """Test SSE assembly with reasoning content in metadata."""
    # Arrange
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(
            content="Answer",
            metadata={
                "provider": "anthropic",
                "role": "assistant",
                "reasoning_content": "Let me think...",
            },
        ),
        SentinelManager.create_done_chunk(),
    ]
    stream = async_iter(chunks)

    # Act
    result = []
    async for chunk_bytes in assembler.assemble_stream(stream):
        result.append(chunk_bytes)

    # Assert
    assert len(result) == 3
    chunk_str = result[0].decode("utf-8")
    assert "reasoning_content" in chunk_str
    assert "Let me think..." in chunk_str
    assert b'"finish_reason": "stop"' in result[1]


@pytest.mark.asyncio
async def test_sse_assembly_handles_dict_content() -> None:
    """Test SSE assembly with dictionary content."""
    # Arrange
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(
            content={"key": "value"},
            metadata={"provider": "openai"},
        ),
        SentinelManager.create_done_chunk(),
    ]
    stream = async_iter(chunks)

    # Act
    result = []
    async for chunk_bytes in assembler.assemble_stream(stream):
        result.append(chunk_bytes)

    # Assert
    assert len(result) == 3
    chunk_str = result[0].decode("utf-8")
    assert "data: " in chunk_str


@pytest.mark.asyncio
async def test_sse_assembly_emits_error_terminal_chunk() -> None:
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(
            content="",
            metadata={
                "provider": "openai",
                "finish_reason": "error",
                "error": {"message": "boom"},
            },
            is_done=True,
        )
    ]

    stream = async_iter(chunks)
    result = [chunk async for chunk in assembler.assemble_stream(stream)]

    assert result
    combined = b"".join(result)
    assert b"boom" in combined
    assert combined.endswith(b"data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_sse_assembler_samples_first_chunk() -> None:
    reset_sampler()
    sampler = get_sampler_instance()
    sampler.sample_rate = 1.0

    assembler = SSEAssembler()
    stream_id = "sample-stream"
    chunks = [
        StreamingContent(
            content="Hello sampler",
            metadata={"provider": "openai", "stream_id": stream_id},
        ),
        SentinelManager.create_done_chunk(),
    ]

    result = []
    async for chunk_bytes in assembler.assemble_stream(async_iter(chunks)):
        result.append(chunk_bytes)

    samples = sampler.get_samples(stream_id=stream_id)
    assert any(sample["type"] == "chunk" for sample in samples)
    reset_sampler()


@pytest.mark.asyncio
async def test_sse_assembler_samples_error_chunks() -> None:
    reset_sampler()
    sampler = get_sampler_instance()
    sampler.sample_rate = 1.0

    assembler = SSEAssembler()
    stream_id = "error-stream"
    error_chunk = StreamingContent(
        content="",
        metadata={
            "provider": "openai",
            "stream_id": stream_id,
            "finish_reason": "error",
            "error": {"type": "BackendError", "message": "boom"},
        },
        is_done=True,
    )

    async for _ in assembler.assemble_stream(async_iter([error_chunk])):
        pass

    samples = sampler.get_samples(stream_id=stream_id)
    assert any(sample["type"] == "error_chunk" for sample in samples)
    reset_sampler()


@pytest.mark.asyncio
async def test_sse_assembler_stops_when_serialized_chunk_contains_done() -> None:
    """Regression: stop streaming immediately when emitted bytes include [DONE].

    StopChunkWithUsage serialization always appends a done sentinel. If an upstream
    component forgets to set is_done=True on such a chunk, the assembler must still
    terminate the stream to prevent post-DONE retransmits.
    """

    assembler = SSEAssembler()
    stop_chunk = StreamingContent(
        content=StopChunkWithUsage({"usage": {"completion_tokens": 1}}),
        metadata={"provider": "openai"},
        is_done=False,
    )
    chunks = [
        StreamingContent(content="hello", metadata={"provider": "openai"}),
        stop_chunk,
        StreamingContent(content="SHOULD_NOT_APPEAR", metadata={"provider": "openai"}),
        SentinelManager.create_done_chunk(),
    ]

    emitted = b"".join(
        [chunk async for chunk in assembler.assemble_stream(async_iter(chunks))]
    )
    decoded = emitted.decode("utf-8", errors="replace")
    assert "SHOULD_NOT_APPEAR" not in decoded
    assert "data: [DONE]" in decoded


@pytest.mark.asyncio
async def test_sse_assembler_does_not_emit_post_done_content() -> None:
    """Ensure content after a [DONE]-containing chunk is never emitted."""

    assembler = SSEAssembler()
    stop_chunk = StreamingContent(
        content=StopChunkWithUsage({"usage": {"completion_tokens": 2}}),
        metadata={"provider": "openai"},
        is_done=False,
    )
    chunks = [
        stop_chunk,
        StreamingContent(content="AFTER_DONE", metadata={"provider": "openai"}),
    ]

    emitted_chunks = [c async for c in assembler.assemble_stream(async_iter(chunks))]
    decoded = b"".join(emitted_chunks).decode("utf-8", errors="replace")
    assert "AFTER_DONE" not in decoded


@pytest.mark.asyncio
async def test_sse_assembler_splits_batched_done_payloads() -> None:
    """Ensure JSON + [DONE] payloads are emitted as separate SSE events.

    Some serializers (e.g. StopChunkWithUsage) produce two SSE events in one bytes
    payload. Yielding them separately improves client compatibility and prevents
    "missing DONE" behaviors in simplistic SSE decoders.
    """

    assembler = SSEAssembler()
    stop_chunk = StreamingContent(
        content=StopChunkWithUsage({"usage": {"completion_tokens": 3}}),
        metadata={"provider": "openai"},
        is_done=False,
    )

    emitted = [c async for c in assembler.assemble_stream(async_iter([stop_chunk]))]
    assert len(emitted) == 2
    assert b"usage" in emitted[0]
    assert emitted[1] == b"data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_sse_assembler_injects_terminal_finish_reason_before_done() -> None:
    """Regression: emit a non-null finish_reason before [DONE] for OpenAI streams."""

    assembler = SSEAssembler()
    openai_like = StreamingContent(
        content={
            "id": "chatcmpl-x",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "test-model",
            "choices": [
                {"index": 0, "finish_reason": None, "delta": {"content": "hi"}}
            ],
        },
        metadata={"provider": "openai"},
        is_done=False,
    )
    chunks = [openai_like, SentinelManager.create_done_chunk()]

    emitted = b"".join([c async for c in assembler.assemble_stream(async_iter(chunks))])
    decoded = emitted.decode("utf-8", errors="replace")
    assert '"finish_reason": "stop"' in decoded
    assert decoded.strip().endswith("data: [DONE]")
