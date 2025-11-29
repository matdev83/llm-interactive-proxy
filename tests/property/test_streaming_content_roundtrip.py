"""
Property-based tests for StreamingContent round-trip serialization.

**Feature: gemini-oauth-streaming-fix, Property 9: StreamingContent round-trip**
**Validates: Requirements 7.1, 7.2, 7.3**

This module tests that StreamingContent objects can be serialized to dict
and deserialized back without loss of information.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.ports.streaming_contracts import StreamingContent
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating StreamingContent components
# ============================================================================


@st.composite
def simple_content_strategy(draw: Any) -> str | dict[str, Any] | bytes:
    """Generate simple content values for StreamingContent.

    Focuses on content types that round-trip cleanly.
    """
    content_type = draw(st.sampled_from(["str", "dict"]))

    if content_type == "str":
        # Generate printable ASCII strings to avoid encoding issues
        return draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N", "P", "S", "Z"),
                    blacklist_characters="\x00",
                ),
                min_size=0,
                max_size=200,
            )
        )
    else:  # dict
        return draw(
            st.fixed_dictionaries(
                {
                    "key": st.text(min_size=1, max_size=20),
                    "value": st.one_of(
                        st.text(max_size=50),
                        st.integers(min_value=-1000, max_value=1000),
                        st.booleans(),
                    ),
                }
            )
        )


@st.composite
def simple_metadata_strategy(draw: Any) -> dict[str, Any]:
    """Generate simple metadata dictionaries that round-trip cleanly."""
    metadata: dict[str, Any] = {}

    # Optionally add provider (common field)
    if draw(st.booleans()):
        metadata["provider"] = draw(
            st.sampled_from(["openai", "anthropic", "gemini", "test"])
        )

    # Optionally add model
    if draw(st.booleans()):
        metadata["model"] = draw(st.sampled_from(["gpt-4", "claude-3", "gemini-pro"]))

    # Optionally add finish_reason
    if draw(st.booleans()):
        metadata["finish_reason"] = draw(
            st.sampled_from([None, "stop", "length", "tool_calls"])
        )

    # Optionally add stream_id
    if draw(st.booleans()):
        metadata["stream_id"] = draw(st.text(min_size=1, max_size=30))

    return metadata


@st.composite
def simple_usage_strategy(draw: Any) -> dict[str, int] | None:
    """Generate simple usage dictionaries."""
    if draw(st.booleans()):
        return None

    prompt_tokens = draw(st.integers(min_value=0, max_value=10000))
    completion_tokens = draw(st.integers(min_value=0, max_value=10000))

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


@st.composite
def roundtrip_streaming_content_strategy(draw: Any) -> StreamingContent:
    """Generate StreamingContent instances suitable for round-trip testing.

    This strategy generates content that should round-trip cleanly through
    to_dict() and from_dict().
    """
    content = draw(simple_content_strategy())
    metadata = draw(simple_metadata_strategy())
    is_done = draw(st.booleans())
    is_cancellation = draw(st.booleans())
    stream_id = draw(st.one_of(st.none(), st.text(min_size=1, max_size=30)))
    usage = draw(simple_usage_strategy())

    return StreamingContent(
        content=content,
        metadata=metadata,
        is_done=is_done,
        is_cancellation=is_cancellation,
        stream_id=stream_id,
        usage=usage,
    )


# ============================================================================
# Property Tests
# ============================================================================


@given(chunk=roundtrip_streaming_content_strategy())
@property_test_settings()
def test_property_9_streaming_content_roundtrip(chunk: StreamingContent) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 9: StreamingContent round-trip**
    **Validates: Requirements 7.1, 7.2, 7.3**

    Property 9: StreamingContent round-trip

    *For any* valid StreamingContent object, serializing it via to_dict()
    and then deserializing via from_dict() SHALL produce an equivalent
    StreamingContent object with the same content, metadata, is_done,
    is_empty, and usage values.
    """
    # Serialize to dict
    serialized = chunk.to_dict()

    # Verify to_dict returns a dict (Requirement 7.1)
    assert isinstance(serialized, dict), "to_dict() must return a dict"

    # Deserialize back to StreamingContent (Requirement 7.2)
    deserialized = StreamingContent.from_dict(serialized)

    # Verify round-trip produces equivalent object (Requirement 7.3)
    assert isinstance(
        deserialized, StreamingContent
    ), "from_dict() must return a StreamingContent"

    # Compare key fields
    # Content comparison - handle bytes specially
    original_content = chunk.content
    restored_content = deserialized.content

    if isinstance(original_content, bytes):
        # Bytes get decoded to string in to_dict()
        try:
            expected = original_content.decode("utf-8")
        except UnicodeDecodeError:
            expected = original_content.decode("latin-1")
        assert (
            restored_content == expected
        ), f"Content mismatch: {restored_content!r} != {expected!r}"
    else:
        assert (
            restored_content == original_content
        ), f"Content mismatch: {restored_content!r} != {original_content!r}"

    # Metadata comparison
    assert (
        deserialized.metadata == chunk.metadata
    ), f"Metadata mismatch: {deserialized.metadata} != {chunk.metadata}"

    # Boolean flags
    assert (
        deserialized.is_done == chunk.is_done
    ), f"is_done mismatch: {deserialized.is_done} != {chunk.is_done}"
    assert (
        deserialized.is_empty == chunk.is_empty
    ), f"is_empty mismatch: {deserialized.is_empty} != {chunk.is_empty}"
    assert (
        deserialized.is_cancellation == chunk.is_cancellation
    ), f"is_cancellation mismatch: {deserialized.is_cancellation} != {chunk.is_cancellation}"

    # Stream ID
    assert (
        deserialized.stream_id == chunk.stream_id
    ), f"stream_id mismatch: {deserialized.stream_id} != {chunk.stream_id}"

    # Usage
    assert (
        deserialized.usage == chunk.usage
    ), f"usage mismatch: {deserialized.usage} != {chunk.usage}"


@given(chunk=roundtrip_streaming_content_strategy())
@property_test_settings()
def test_to_dict_returns_plain_dict(chunk: StreamingContent) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 9: StreamingContent round-trip**
    **Validates: Requirements 7.1**

    Verify that to_dict() returns a plain dict (not a subclass).
    """
    serialized = chunk.to_dict()

    # Must be exactly dict, not a subclass
    assert (
        type(serialized) is dict
    ), f"to_dict() returned {type(serialized).__name__}, expected dict"

    # Must contain expected keys
    expected_keys = {
        "content",
        "metadata",
        "is_done",
        "is_empty",
        "stream_id",
        "is_cancellation",
        "usage",
    }
    assert (
        set(serialized.keys()) == expected_keys
    ), f"to_dict() keys mismatch: {set(serialized.keys())} != {expected_keys}"


@given(chunk=roundtrip_streaming_content_strategy())
@property_test_settings()
def test_double_roundtrip_is_stable(chunk: StreamingContent) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 9: StreamingContent round-trip**
    **Validates: Requirements 7.3**

    Verify that multiple round-trips produce stable results.
    """
    # First round-trip
    dict1 = chunk.to_dict()
    restored1 = StreamingContent.from_dict(dict1)

    # Second round-trip
    dict2 = restored1.to_dict()
    restored2 = StreamingContent.from_dict(dict2)

    # The two serialized forms should be identical
    assert dict1 == dict2, "Double round-trip produced different dicts"

    # The two restored objects should have identical to_dict() output
    assert (
        restored1.to_dict() == restored2.to_dict()
    ), "Double round-trip produced different StreamingContent objects"
