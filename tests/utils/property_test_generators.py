# mypy: ignore-errors
"""
Property-based test generators and utilities for streaming pipeline testing.

This module provides Hypothesis strategies and utilities for generating
test data for property-based testing of the streaming pipeline.

Feature: streaming-pipeline-refactor, Task 21: Property-based test infrastructure
"""

from typing import Any

from hypothesis import strategies as st
from src.core.ports.streaming_contracts import StreamingContent

# ============================================================================
# Core Content Strategies
# ============================================================================


@st.composite
def valid_content_strategy(draw: Any) -> str | dict | bytes:
    """Generate valid content values for StreamingContent.

    Returns:
        A valid content value (str, dict, or bytes)
    """
    content_type = draw(st.sampled_from(["str", "dict", "bytes"]))

    if content_type == "str":
        return draw(st.text(min_size=0, max_size=500))
    elif content_type == "dict":
        return draw(
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                st.one_of(
                    st.text(max_size=100),
                    st.integers(),
                    st.booleans(),
                    st.none(),
                ),
                min_size=0,
                max_size=10,
            )
        )
    else:  # bytes
        return draw(st.binary(min_size=0, max_size=500))


@st.composite
def text_content_strategy(draw: Any) -> str:
    """Generate text content for StreamingContent.

    Returns:
        A text string
    """
    return draw(st.text(min_size=0, max_size=500))


@st.composite
def dict_content_strategy(draw: Any) -> dict[str, Any]:
    """Generate dictionary content for StreamingContent.

    Returns:
        A dictionary with string keys
    """
    return draw(
        st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.one_of(
                st.text(max_size=100),
                st.integers(),
                st.booleans(),
                st.none(),
            ),
            min_size=0,
            max_size=10,
        )
    )


@st.composite
def bytes_content_strategy(draw: Any) -> bytes:
    """Generate bytes content for StreamingContent.

    Returns:
        A bytes object
    """
    return draw(st.binary(min_size=0, max_size=500))


# ============================================================================
# Metadata Strategies
# ============================================================================


@st.composite
def valid_metadata_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid metadata dictionaries conforming to the schema.

    Returns:
        A valid metadata dictionary
    """
    metadata: dict[str, Any] = {}

    # Optionally add stream_id (required in many contexts)
    if draw(st.booleans()):
        metadata["stream_id"] = draw(st.text(min_size=1, max_size=50))

    # Optionally add provider
    if draw(st.booleans()):
        metadata["provider"] = draw(
            st.sampled_from(["openai", "anthropic", "gemini", "test", "mock"])
        )

    # Optionally add model
    if draw(st.booleans()):
        metadata["model"] = draw(
            st.sampled_from(
                [
                    "gpt-4",
                    "gpt-3.5-turbo",
                    "claude-3-opus",
                    "claude-3-sonnet",
                    "gemini-pro",
                    "gemini-ultra",
                ]
            )
        )

    # Optionally add role
    if draw(st.booleans()):
        metadata["role"] = draw(
            st.sampled_from(["assistant", "user", "system", "tool", "model"])
        )

    # Optionally add finish_reason
    if draw(st.booleans()):
        metadata["finish_reason"] = draw(
            st.sampled_from([None, "stop", "length", "tool_calls", "error"])
        )

    # Optionally add reasoning_content
    if draw(st.booleans()):
        metadata["reasoning_content"] = draw(
            st.one_of(st.none(), st.text(min_size=1, max_size=200))
        )

    # Optionally add tool_calls
    if draw(st.booleans()):
        metadata["tool_calls"] = draw(tool_calls_strategy())

    # Optionally add index
    if draw(st.booleans()):
        metadata["index"] = draw(st.integers(min_value=0, max_value=10))

    # Optionally add created timestamp
    if draw(st.booleans()):
        metadata["created"] = draw(
            st.integers(min_value=1000000000, max_value=2000000000)
        )

    # Optionally add id
    if draw(st.booleans()):
        metadata["id"] = draw(st.text(min_size=1, max_size=50))

    return metadata


@st.composite
def minimal_metadata_strategy(draw: Any) -> dict[str, Any]:
    """Generate minimal valid metadata (only required fields).

    Returns:
        A minimal metadata dictionary
    """
    return {
        "provider": draw(st.sampled_from(["openai", "anthropic", "gemini", "test"])),
    }


@st.composite
def tool_calls_strategy(draw: Any) -> list[dict[str, Any]]:
    """Generate valid tool_calls list.

    Returns:
        A list of tool call dictionaries
    """
    num_calls = draw(st.integers(min_value=0, max_value=5))
    tool_calls = []

    for _i in range(num_calls):
        tool_call = {
            "id": draw(st.text(min_size=1, max_size=30)),
            "type": "function",
            "function": {
                "name": draw(st.text(min_size=1, max_size=50)),
                "arguments": draw(st.text(min_size=0, max_size=200)),
            },
        }
        tool_calls.append(tool_call)

    return tool_calls


# ============================================================================
# StreamingContent Strategies
# ============================================================================


@st.composite
def streaming_content_strategy(draw: Any) -> StreamingContent:
    """Generate valid StreamingContent instances.

    Returns:
        A valid StreamingContent instance
    """
    content = draw(valid_content_strategy())
    metadata = draw(valid_metadata_strategy())
    is_done = draw(st.booleans())
    is_empty = draw(st.booleans())
    stream_id = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))
    is_cancellation = draw(st.booleans())

    return StreamingContent(
        content=content,
        metadata=metadata,
        is_done=is_done,
        is_empty=is_empty,
        stream_id=stream_id,
        is_cancellation=is_cancellation,
    )


@st.composite
def non_done_streaming_content_strategy(draw: Any) -> StreamingContent:
    """Generate StreamingContent that is not a done marker.

    Returns:
        A non-terminal StreamingContent instance
    """
    chunk = draw(streaming_content_strategy())
    chunk.is_done = False
    return chunk


@st.composite
def done_streaming_content_strategy(draw: Any) -> StreamingContent:
    """Generate StreamingContent that is a done marker.

    Returns:
        A terminal StreamingContent instance
    """
    chunk = draw(streaming_content_strategy())
    chunk.is_done = True
    chunk.metadata["finish_reason"] = draw(
        st.sampled_from(["stop", "length", "tool_calls", "error"])
    )
    return chunk


@st.composite
def streaming_content_with_reasoning_strategy(draw: Any) -> StreamingContent:
    """Generate StreamingContent with reasoning content in metadata.

    Returns:
        A StreamingContent instance with reasoning_content
    """
    chunk = draw(streaming_content_strategy())
    chunk.metadata["reasoning_content"] = draw(st.text(min_size=1, max_size=200))
    return chunk


@st.composite
def streaming_content_with_tool_calls_strategy(draw: Any) -> StreamingContent:
    """Generate StreamingContent with tool calls in metadata.

    Returns:
        A StreamingContent instance with tool_calls
    """
    chunk = draw(streaming_content_strategy())
    chunk.metadata["tool_calls"] = draw(tool_calls_strategy())
    return chunk


# ============================================================================
# Chunk Pattern Strategies
# ============================================================================


@st.composite
def chunk_stream_strategy(
    draw: Any, min_size: int = 1, max_size: int = 50
) -> list[StreamingContent]:
    """Generate a stream of chunks (list of StreamingContent).

    Args:
        draw: Hypothesis draw function
        min_size: Minimum number of chunks
        max_size: Maximum number of chunks

    Returns:
        A list of StreamingContent chunks
    """
    return draw(
        st.lists(
            streaming_content_strategy(),
            min_size=min_size,
            max_size=max_size,
        )
    )


@st.composite
def chunk_stream_with_done_strategy(
    draw: Any, min_size: int = 1, max_size: int = 50
) -> list[StreamingContent]:
    """Generate a stream of chunks with a done marker at the end.

    Args:
        draw: Hypothesis draw function
        min_size: Minimum number of non-done chunks
        max_size: Maximum number of non-done chunks

    Returns:
        A list of StreamingContent chunks ending with a done marker
    """
    # Generate non-done chunks
    chunks = draw(
        st.lists(
            non_done_streaming_content_strategy(),
            min_size=min_size,
            max_size=max_size,
        )
    )

    # Add a done marker at the end
    done_chunk = draw(done_streaming_content_strategy())
    chunks.append(done_chunk)

    return chunks


@st.composite
def interleaved_chunk_stream_strategy(
    draw: Any, num_streams: int = 2, chunks_per_stream: int = 10
) -> list[tuple[str, StreamingContent]]:
    """Generate interleaved chunks from multiple streams.

    This is useful for testing stream isolation properties.

    Args:
        draw: Hypothesis draw function
        num_streams: Number of concurrent streams
        chunks_per_stream: Number of chunks per stream

    Returns:
        A list of (stream_id, chunk) tuples in interleaved order
    """
    # Generate stream IDs
    stream_ids = [f"stream-{i}" for i in range(num_streams)]

    # Generate chunks for each stream
    all_chunks: list[tuple[str, StreamingContent]] = []
    for stream_id in stream_ids:
        chunks = draw(
            st.lists(
                streaming_content_strategy(),
                min_size=chunks_per_stream,
                max_size=chunks_per_stream,
            )
        )
        for chunk in chunks:
            chunk.stream_id = stream_id
            all_chunks.append((stream_id, chunk))

    # Shuffle to interleave
    draw(st.randoms()).shuffle(all_chunks)

    return all_chunks


# ============================================================================
# Error Strategies
# ============================================================================


@st.composite
def error_type_strategy(draw: Any) -> str:
    """Generate error type names for testing.

    Returns:
        An error type string
    """
    return draw(
        st.sampled_from(
            [
                "timeout",
                "http_error_400",
                "http_error_401",
                "http_error_403",
                "http_error_404",
                "http_error_429",
                "http_error_500",
                "http_error_502",
                "http_error_503",
                "connect_error",
                "json_error",
                "generic_error",
            ]
        )
    )


@st.composite
def provider_strategy(draw: Any) -> str:
    """Generate provider names for testing.

    Returns:
        A provider name string
    """
    return draw(st.sampled_from(["openai", "anthropic", "gemini", "test", "mock"]))


@st.composite
def stream_id_strategy(draw: Any) -> str | None:
    """Generate stream IDs for testing.

    Returns:
        A stream ID string or None
    """
    return draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))


# ============================================================================
# Backend-Specific Strategies
# ============================================================================


@st.composite
def openai_chunk_strategy(draw: Any) -> dict[str, Any]:
    """Generate OpenAI-style streaming chunks.

    Returns:
        A dictionary representing an OpenAI streaming chunk
    """
    chunk = {
        "id": draw(st.text(min_size=1, max_size=50)),
        "object": "chat.completion.chunk",
        "created": draw(st.integers(min_value=1000000000, max_value=2000000000)),
        "model": draw(st.sampled_from(["gpt-4", "gpt-3.5-turbo"])),
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": draw(
                    st.sampled_from([None, "stop", "length", "tool_calls"])
                ),
            }
        ],
    }

    # Optionally add content
    if draw(st.booleans()):
        chunk["choices"][0]["delta"]["content"] = draw(st.text(max_size=200))

    # Optionally add role
    if draw(st.booleans()):
        chunk["choices"][0]["delta"]["role"] = "assistant"

    # Optionally add tool calls
    if draw(st.booleans()):
        chunk["choices"][0]["delta"]["tool_calls"] = draw(tool_calls_strategy())

    return chunk


@st.composite
def anthropic_event_strategy(draw: Any) -> dict[str, Any]:
    """Generate Anthropic-style streaming events.

    Returns:
        A dictionary representing an Anthropic streaming event
    """
    event_type = draw(
        st.sampled_from(
            [
                "message_start",
                "content_block_start",
                "content_block_delta",
                "content_block_stop",
                "message_delta",
                "message_stop",
            ]
        )
    )

    event = {"type": event_type}

    if event_type == "message_start":
        event["message"] = {
            "id": draw(st.text(min_size=1, max_size=50)),
            "type": "message",
            "role": "assistant",
            "model": draw(st.sampled_from(["claude-3-opus", "claude-3-sonnet"])),
        }
    elif event_type == "content_block_delta":
        event["delta"] = {"type": "text_delta", "text": draw(st.text(max_size=200))}
    elif event_type == "message_delta":
        event["delta"] = {
            "stop_reason": draw(st.sampled_from([None, "end_turn", "max_tokens"]))
        }

    return event


@st.composite
def gemini_chunk_strategy(draw: Any) -> dict[str, Any]:
    """Generate Gemini-style streaming chunks.

    Returns:
        A dictionary representing a Gemini streaming chunk
    """
    chunk = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": draw(st.text(max_size=200))}],
                    "role": "model",
                },
                "finishReason": draw(
                    st.sampled_from([None, "STOP", "MAX_TOKENS", "SAFETY"])
                ),
            }
        ]
    }

    # Optionally add function call
    if draw(st.booleans()):
        chunk["candidates"][0]["content"]["parts"].append(
            {
                "functionCall": {
                    "name": draw(st.text(min_size=1, max_size=50)),
                    "args": draw(dict_content_strategy()),
                }
            }
        )

    return chunk


# ============================================================================
# Utility Functions
# ============================================================================


def create_test_chunk(
    content: str = "test",
    provider: str = "test",
    stream_id: str | None = None,
    is_done: bool = False,
) -> StreamingContent:
    """Create a simple test chunk for unit tests.

    Args:
        content: The content string
        provider: The provider name
        stream_id: Optional stream ID
        is_done: Whether this is a done marker

    Returns:
        A StreamingContent instance
    """
    return StreamingContent(
        content=content,
        metadata={"provider": provider},
        is_done=is_done,
        stream_id=stream_id,
    )


def create_done_chunk(
    provider: str = "test", stream_id: str | None = None
) -> StreamingContent:
    """Create a done marker chunk for testing.

    Args:
        provider: The provider name
        stream_id: Optional stream ID

    Returns:
        A terminal StreamingContent instance
    """
    return StreamingContent(
        content="[DONE]",
        metadata={"provider": provider, "finish_reason": "stop"},
        is_done=True,
        stream_id=stream_id,
    )


def create_error_chunk(
    error_message: str = "Test error",
    provider: str = "test",
    stream_id: str | None = None,
) -> StreamingContent:
    """Create an error chunk for testing.

    Args:
        error_message: The error message
        provider: The provider name
        stream_id: Optional stream ID

    Returns:
        A terminal error StreamingContent instance
    """
    return StreamingContent(
        content="",
        metadata={
            "provider": provider,
            "error": {
                "type": "TestError",
                "message": error_message,
                "code": "test_error",
                "retryable": False,
            },
            "finish_reason": "error",
        },
        is_done=True,
        stream_id=stream_id,
    )
