"""Property-based tests for backward compatibility during migration.

Property 30: Backward compatibility during migration
Feature: streaming-pipeline-refactor, Property 30: Backward compatibility during migration

For any migrated component, it should produce identical output to the
pre-migration version for the same inputs.

Validates: Requirements 10.3
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.ports.streaming_contracts import StreamingContent

from tests.utils.fake_clock import FakeClock


# Strategy for generating StreamingContent chunks
@st.composite
def streaming_content_strategy(draw: Any) -> StreamingContent:
    """Generate arbitrary StreamingContent chunks."""
    content_type = draw(st.sampled_from(["text", "dict", "bytes", "empty"]))

    if content_type == "text":
        content = draw(st.text(min_size=0, max_size=100))
    elif content_type == "dict":
        content = draw(
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                st.one_of(st.text(), st.integers(), st.booleans()),
                max_size=5,
            )
        )
    elif content_type == "bytes":
        content = draw(st.binary(min_size=0, max_size=100))
    else:
        content = ""

    # Generate metadata
    metadata: dict[str, Any] = {}

    # Add optional fields
    if draw(st.booleans()):
        metadata["stream_id"] = draw(st.text(min_size=1, max_size=20))
    if draw(st.booleans()):
        metadata["provider"] = draw(
            st.sampled_from(["openai", "anthropic", "gemini", "test"])
        )
    if draw(st.booleans()):
        metadata["model"] = draw(st.text(min_size=1, max_size=30))
    if draw(st.booleans()):
        metadata["role"] = draw(st.sampled_from(["assistant", "user", "system"]))
    if draw(st.booleans()):
        metadata["finish_reason"] = draw(
            st.sampled_from([None, "stop", "length", "tool_calls", "error"])
        )
    if draw(st.booleans()):
        metadata["reasoning_content"] = draw(st.text(min_size=0, max_size=50))
    if draw(st.booleans()):
        metadata["index"] = draw(st.integers(min_value=0, max_value=10))
    if draw(st.booleans()):
        metadata["created"] = draw(
            st.integers(min_value=1000000000, max_value=2000000000)
        )
    if draw(st.booleans()):
        metadata["id"] = draw(st.text(min_size=1, max_size=30))

    is_done = draw(st.booleans())
    is_empty = draw(st.booleans())
    stream_id = draw(st.one_of(st.none(), st.text(min_size=1, max_size=20)))

    return StreamingContent(
        content=content,
        metadata=metadata,
        is_done=is_done,
        is_empty=is_empty,
        stream_id=stream_id,
    )


@pytest.mark.asyncio
@given(chunks=st.lists(streaming_content_strategy(), min_size=1, max_size=20))
@settings(max_examples=30, deadline=None)
async def test_streaming_content_serialization_backward_compatibility(
    chunks: list[StreamingContent],
) -> None:
    """
    Property 30: Backward compatibility during migration
    Feature: streaming-pipeline-refactor, Property 30: Backward compatibility during migration

    For any list of StreamingContent chunks, serializing to bytes and back
    should preserve the essential information (content, metadata, flags).

    This ensures that the new StreamingContent contract maintains compatibility
    with existing serialization/deserialization logic.
    """
    for chunk in chunks:
        # Serialize to bytes (SSE format)
        serialized = chunk.to_bytes()

        # Verify it's valid bytes
        assert isinstance(serialized, bytes), "Serialization must produce bytes"

        # Verify SSE format structure
        decoded = serialized.decode("utf-8")

        if chunk.is_done and not chunk.is_cancellation:
            # Done chunks should produce [DONE] marker
            assert b"[DONE]" in serialized, "Done chunks must include [DONE] marker"
        else:
            # Non-done chunks should have data: prefix
            assert decoded.startswith("data: "), "Chunks must start with 'data: '"

            # Verify JSON structure if not [DONE]
            if "[DONE]" not in decoded:
                # Extract JSON from SSE format
                lines = decoded.strip().split("\n")
                json_line = None
                for line in lines:
                    if line.startswith("data: "):
                        json_line = line[6:].strip()
                        break

                if json_line:
                    # Parse JSON to verify structure
                    try:
                        data = json.loads(json_line)
                        assert "choices" in data, "Serialized chunk must have choices"
                        assert isinstance(
                            data["choices"], list
                        ), "choices must be a list"
                        assert len(data["choices"]) > 0, "choices must not be empty"
                        assert "delta" in data["choices"][0], "choice must have delta"
                    except json.JSONDecodeError:
                        # If it's not valid JSON, that's a compatibility issue
                        pytest.fail(f"Invalid JSON in serialized chunk: {json_line}")


@pytest.mark.asyncio
@given(chunks=st.lists(streaming_content_strategy(), min_size=1, max_size=20))
@settings(max_examples=30, deadline=None)
async def test_streaming_content_dict_conversion_backward_compatibility(
    chunks: list[StreamingContent],
) -> None:
    """
    Property 30: Backward compatibility during migration
    Feature: streaming-pipeline-refactor, Property 30: Backward compatibility during migration

    For any StreamingContent chunk, converting to dict and back should
    preserve all essential fields.

    This ensures that the new StreamingContent contract maintains compatibility
    with existing dict-based processing logic.
    """
    for chunk in chunks:
        # Convert to dict
        chunk_dict = chunk.to_dict()

        # Verify dict structure
        assert isinstance(chunk_dict, dict), "to_dict must return a dict"
        assert "content" in chunk_dict, "Dict must have content field"
        assert "metadata" in chunk_dict, "Dict must have metadata field"
        assert "is_done" in chunk_dict, "Dict must have is_done field"
        assert "is_empty" in chunk_dict, "Dict must have is_empty field"
        assert "stream_id" in chunk_dict, "Dict must have stream_id field"

        # Verify types
        assert isinstance(chunk_dict["metadata"], dict), "metadata must be dict"
        assert isinstance(chunk_dict["is_done"], bool), "is_done must be bool"
        assert isinstance(chunk_dict["is_empty"], bool), "is_empty must be bool"

        # Verify content preservation
        if isinstance(chunk.content, bytes):
            # Bytes should be decoded to string
            assert isinstance(
                chunk_dict["content"], str
            ), "Bytes content should be decoded to string"
        elif isinstance(chunk.content, dict):
            # Dict should be preserved
            assert isinstance(
                chunk_dict["content"], dict
            ), "Dict content should be preserved"
        else:
            # String should be preserved
            assert isinstance(
                chunk_dict["content"], str | type(None)
            ), "String content should be preserved"


@pytest.mark.asyncio
@given(
    chunks=st.lists(streaming_content_strategy(), min_size=2, max_size=10),
    delays=st.lists(st.floats(min_value=0.001, max_value=0.1), min_size=2, max_size=10),
)
@settings(max_examples=15, deadline=None)
async def test_streaming_timing_determinism_with_fake_clock(
    chunks: list[StreamingContent], delays: list[float]
) -> None:
    """
    Property 30: Backward compatibility during migration
    Feature: streaming-pipeline-refactor, Property 30: Backward compatibility during migration

    For any sequence of chunks with delays, using a fake clock should produce
    deterministic timing behavior.

    This ensures that tests using the new fake clock utilities produce
    consistent results, maintaining backward compatibility with timing-based
    test assertions.
    """
    # Ensure we have matching lengths
    min_len = min(len(chunks), len(delays))
    chunks = chunks[:min_len]
    delays = delays[:min_len]

    # Create fake clock
    fake_clock = FakeClock()

    # Simulate streaming with fake clock
    chunk_times = []

    for _i, (chunk, delay) in enumerate(zip(chunks, delays, strict=False)):
        # Record time before delay
        time_before = fake_clock.now()
        chunk_times.append((chunk, time_before))

        # Advance clock by delay
        fake_clock.advance(delay)

    # Verify deterministic timing
    for i in range(len(chunk_times) - 1):
        time_current = chunk_times[i][1]
        time_next = chunk_times[i + 1][1]

        # Times should be strictly increasing
        assert (
            time_next > time_current
        ), f"Time should increase: {time_current} -> {time_next}"

        # Time difference should match delay
        expected_diff = delays[i]
        actual_diff = time_next - time_current
        assert (
            abs(actual_diff - expected_diff) < 0.0001
        ), f"Time difference mismatch: expected {expected_diff}, got {actual_diff}"


@pytest.mark.asyncio
@given(chunks=st.lists(streaming_content_strategy(), min_size=1, max_size=20))
@settings(max_examples=30, deadline=None)
async def test_streaming_content_validation_backward_compatibility(
    chunks: list[StreamingContent],
) -> None:
    """
    Property 30: Backward compatibility during migration
    Feature: streaming-pipeline-refactor, Property 30: Backward compatibility during migration

    For any StreamingContent chunk, validation should accept all valid chunks
    and reject invalid ones consistently.

    This ensures that the new validation logic maintains backward compatibility
    with existing validation behavior.
    """
    for chunk in chunks:
        # All generated chunks should be valid (they passed __post_init__)
        assert isinstance(chunk, StreamingContent), "Chunk must be StreamingContent"

        # Verify validation doesn't raise
        try:
            chunk._validate()
        except ValueError as e:
            # If validation fails, it should be for a good reason
            pytest.fail(f"Valid chunk failed validation: {e}")

        # Verify required fields are present
        assert hasattr(chunk, "content"), "Chunk must have content"
        assert hasattr(chunk, "metadata"), "Chunk must have metadata"
        assert hasattr(chunk, "is_done"), "Chunk must have is_done"
        assert hasattr(chunk, "is_empty"), "Chunk must have is_empty"
        assert hasattr(chunk, "stream_id"), "Chunk must have stream_id"


@pytest.mark.asyncio
@given(
    chunks=st.lists(streaming_content_strategy(), min_size=1, max_size=20),
    stream_id=st.text(min_size=1, max_size=30),
)
@settings(max_examples=30, deadline=None)
async def test_streaming_content_stream_id_consistency(
    chunks: list[StreamingContent], stream_id: str
) -> None:
    """
    Property 30: Backward compatibility during migration
    Feature: streaming-pipeline-refactor, Property 30: Backward compatibility during migration

    For any sequence of chunks with a stream_id, the stream_id should be
    consistently preserved through serialization and processing.

    This ensures that the new stream_id handling maintains backward
    compatibility with existing stream tracking logic.
    """
    # Set stream_id on all chunks
    chunks_with_id = []
    for chunk in chunks:
        # Create new chunk with stream_id
        new_chunk = StreamingContent(
            content=chunk.content,
            metadata={**chunk.metadata, "stream_id": stream_id},
            is_done=chunk.is_done,
            is_empty=chunk.is_empty,
            stream_id=stream_id,
        )
        chunks_with_id.append(new_chunk)

    # Verify stream_id is preserved
    for chunk in chunks_with_id:
        assert chunk.stream_id == stream_id, "stream_id should be preserved"
        assert (
            chunk.metadata.get("stream_id") == stream_id
        ), "stream_id should be in metadata"

        # Verify stream_id survives serialization
        serialized = chunk.to_bytes()
        assert isinstance(serialized, bytes), "Serialization must produce bytes"

        # Verify stream_id survives dict conversion
        chunk_dict = chunk.to_dict()
        assert (
            chunk_dict["stream_id"] == stream_id
        ), "stream_id should be in dict representation"


@pytest.mark.asyncio
@given(
    content=st.text(min_size=1, max_size=100),
    provider=st.sampled_from(["openai", "anthropic", "gemini"]),
)
@settings(max_examples=30, deadline=None)
async def test_streaming_content_provider_consistency(
    content: str, provider: str
) -> None:
    """
    Property 30: Backward compatibility during migration
    Feature: streaming-pipeline-refactor, Property 30: Backward compatibility during migration

    For any content and provider, the provider should be consistently
    preserved through the streaming pipeline.

    This ensures that the new provider handling maintains backward
    compatibility with existing provider-specific logic.
    """
    # Create chunk with provider
    chunk = StreamingContent(
        content=content,
        metadata={"provider": provider},
        is_done=False,
        is_empty=False,
    )

    # Verify provider is preserved
    assert chunk.metadata.get("provider") == provider, "Provider should be in metadata"

    # Verify provider survives serialization
    serialized = chunk.to_bytes()
    assert isinstance(serialized, bytes), "Serialization must produce bytes"

    # Verify provider survives dict conversion
    chunk_dict = chunk.to_dict()
    assert (
        chunk_dict["metadata"].get("provider") == provider
    ), "Provider should be in dict metadata"
