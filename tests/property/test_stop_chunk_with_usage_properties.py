"""
Property-based tests for StopChunkWithUsage serialization protection.

This module contains property tests for:
- Property 3: StopChunkWithUsage str() protection (Requirements 1.5)
- Property 8: StopChunkWithUsage serialization safety (Requirements 6.1, 6.2)
- Property 10: StopChunkWithUsage round-trip (Requirements 7.4)
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.ports.streaming_contracts import (
    StopChunkWithUsage,
    UsageChunkLeakError,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating StopChunkWithUsage components
# ============================================================================


@st.composite
def usage_strategy(draw: Any) -> dict[str, int]:
    """Generate valid usage dictionaries."""
    prompt_tokens = draw(st.integers(min_value=0, max_value=100000))
    completion_tokens = draw(st.integers(min_value=0, max_value=100000))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


@st.composite
def choice_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid choice dictionaries for OpenAI format."""
    index = draw(st.integers(min_value=0, max_value=10))
    role = draw(st.sampled_from(["assistant", "user", "system"]))
    finish_reason = draw(st.sampled_from(["stop", "tool_calls", "length", None]))

    delta: dict[str, Any] = {"role": role}

    # Optionally add content
    if draw(st.booleans()):
        delta["content"] = draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N", "P", "S", "Z"),
                    blacklist_characters="\x00",
                ),
                min_size=0,
                max_size=100,
            )
        )

    return {
        "index": index,
        "delta": delta,
        "finish_reason": finish_reason,
    }


@st.composite
def stop_chunk_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid stop chunk dictionaries with usage data.

    This generates chunks in OpenAI format with:
    - id: chatcmpl-xxx format
    - object: chat.completion.chunk
    - created: Unix timestamp
    - model: Model name
    - choices: List of choice objects
    - usage: Token usage data
    """
    # Generate a valid chunk ID
    chunk_id = f"chatcmpl-{draw(st.text(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', min_size=8, max_size=20))}"

    # Generate timestamp
    created = draw(st.integers(min_value=1000000000, max_value=2000000000))

    # Generate model name
    model = draw(
        st.sampled_from(
            [
                "gpt-4",
                "gpt-3.5-turbo",
                "gemini-pro",
                "gemini-3-pro-high",
                "claude-3-opus",
                "claude-3-sonnet",
            ]
        )
    )

    # Generate choices (at least one)
    choices = [draw(choice_strategy())]

    # Generate usage
    usage = draw(usage_strategy())

    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": choices,
        "usage": usage,
    }


@st.composite
def stop_chunk_with_usage_strategy(draw: Any) -> StopChunkWithUsage:
    """Generate StopChunkWithUsage instances for testing."""
    chunk_dict = draw(stop_chunk_strategy())
    return StopChunkWithUsage(chunk_dict)


# ============================================================================
# Property 3: StopChunkWithUsage str() protection
# ============================================================================


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_3_str_raises_usage_chunk_leak_error(
    chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 3: StopChunkWithUsage str() protection**
    **Validates: Requirements 1.5**

    Property 3: StopChunkWithUsage str() protection

    *For any* StopChunkWithUsage instance, calling str() on it SHALL raise
    UsageChunkLeakError with the chunk ID in the error message.
    """
    # Calling str() should raise UsageChunkLeakError
    with pytest.raises(UsageChunkLeakError) as exc_info:
        str(chunk)

    # The error message should contain the chunk ID
    chunk_id = chunk.get("id")
    assert chunk_id in str(exc_info.value), (
        f"Error message should contain chunk ID '{chunk_id}', "
        f"but got: {exc_info.value}"
    )


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_3_fstring_raises_usage_chunk_leak_error(
    chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 3: StopChunkWithUsage str() protection**
    **Validates: Requirements 1.5**

    *For any* StopChunkWithUsage instance, using it in an f-string SHALL raise
    UsageChunkLeakError.
    """
    # Using in f-string should raise UsageChunkLeakError
    with pytest.raises(UsageChunkLeakError):
        _ = f"Content: {chunk}"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_3_format_raises_usage_chunk_leak_error(
    chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 3: StopChunkWithUsage str() protection**
    **Validates: Requirements 1.5**

    *For any* StopChunkWithUsage instance, using it in % formatting SHALL raise
    UsageChunkLeakError.
    """
    # Using in % formatting should raise UsageChunkLeakError
    with pytest.raises(UsageChunkLeakError):
        _ = "Content: {}".format(chunk)  # noqa: UP032


# ============================================================================
# Property 8: StopChunkWithUsage serialization safety
# ============================================================================


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_8_json_dumps_with_dict_conversion(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 8: StopChunkWithUsage serialization safety**
    **Validates: Requirements 6.1, 6.2**

    Property 8: StopChunkWithUsage serialization safety

    *For any* StopChunkWithUsage instance, calling json.dumps() on it
    (after explicit dict() conversion) SHALL produce valid JSON.
    """
    # Convert to plain dict first, then serialize
    plain_dict = dict(chunk)

    # json.dumps should work without raising
    json_str = json.dumps(plain_dict)

    # Result should be valid JSON
    assert isinstance(json_str, str), "json.dumps should return a string"

    # Should be parseable back to dict
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict), "Parsed JSON should be a dict"

    # Should contain the same data
    assert parsed == plain_dict, "Round-trip through JSON should preserve data"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_8_safe_json_dumps(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 8: StopChunkWithUsage serialization safety**
    **Validates: Requirements 6.1, 6.2**

    *For any* StopChunkWithUsage instance, calling safe_json_dumps() SHALL
    produce valid JSON without raising UsageChunkLeakError.
    """
    # safe_json_dumps should work without raising
    json_str = StopChunkWithUsage.safe_json_dumps(chunk)

    # Result should be valid JSON
    assert isinstance(json_str, str), "safe_json_dumps should return a string"

    # Should be parseable back to dict
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict), "Parsed JSON should be a dict"

    # Should contain the same data
    assert parsed == dict(chunk), "safe_json_dumps should preserve data"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_8_iteration_does_not_trigger_str(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 8: StopChunkWithUsage serialization safety**
    **Validates: Requirements 6.2**

    *For any* StopChunkWithUsage instance, direct iteration SHALL be prevented
    to avoid accidental serialization via json.dumps(). Legitimate access should
    use dict(chunk) or chunk.to_plain_dict().
    """
    # items() should raise TypeError to prevent json.dumps() serialization
    with pytest.raises(TypeError, match="Cannot directly serialize StopChunkWithUsage"):
        list(chunk.items())

    # But dict() conversion should work for legitimate use
    plain_dict = dict(chunk)
    assert isinstance(plain_dict, dict), "dict() conversion should work"
    assert not isinstance(plain_dict, StopChunkWithUsage), "Should be plain dict"
    
    # And we can iterate over the plain dict
    items = list(plain_dict.items())
    assert isinstance(items, list), "Plain dict items() should work"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_8_to_plain_dict_returns_plain_dict(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 8: StopChunkWithUsage serialization safety**
    **Validates: Requirements 6.1**

    *For any* StopChunkWithUsage instance, to_plain_dict() SHALL return a
    true plain dict (not a subclass).
    """
    plain = chunk.to_plain_dict()

    # Must be exactly dict, not a subclass
    assert (
        type(plain) is dict
    ), f"to_plain_dict() returned {type(plain).__name__}, expected dict"

    # Should not be a StopChunkWithUsage
    assert not isinstance(
        plain, StopChunkWithUsage
    ), "to_plain_dict() should not return a StopChunkWithUsage"

    # Should contain the same data
    assert plain == dict(chunk), "to_plain_dict() should preserve data"


# ============================================================================
# Property 10: StopChunkWithUsage round-trip
# ============================================================================


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_10_roundtrip_via_to_plain_dict_and_wrap(
    chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 10: StopChunkWithUsage round-trip**
    **Validates: Requirements 7.4**

    Property 10: StopChunkWithUsage round-trip

    *For any* valid StopChunkWithUsage object, serializing it via to_plain_dict()
    and then wrapping it again via StopChunkWithUsage.wrap() SHALL produce an
    equivalent StopChunkWithUsage object with the same keys and values.
    """
    # Serialize to plain dict
    plain = chunk.to_plain_dict()

    # Wrap again
    restored = StopChunkWithUsage.wrap(plain)

    # Should be a StopChunkWithUsage (since it has usage and choices)
    assert isinstance(
        restored, StopChunkWithUsage
    ), f"wrap() should return StopChunkWithUsage, got {type(restored).__name__}"

    # Should have the same keys
    assert set(restored.keys()) == set(
        chunk.keys()
    ), f"Keys mismatch: {set(restored.keys())} != {set(chunk.keys())}"

    # Should have the same values
    for key in chunk:
        assert (
            restored[key] == chunk[key]
        ), f"Value mismatch for key '{key}': {restored[key]} != {chunk[key]}"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_10_roundtrip_via_from_dict(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 10: StopChunkWithUsage round-trip**
    **Validates: Requirements 7.4**

    *For any* valid StopChunkWithUsage object, serializing it via to_plain_dict()
    and then deserializing via from_dict() SHALL produce an equivalent
    StopChunkWithUsage object.
    """
    # Serialize to plain dict
    plain = chunk.to_plain_dict()

    # Deserialize via from_dict
    restored = StopChunkWithUsage.from_dict(plain)

    # Should be a StopChunkWithUsage
    assert isinstance(
        restored, StopChunkWithUsage
    ), f"from_dict() should return StopChunkWithUsage, got {type(restored).__name__}"

    # Should have the same keys
    assert set(restored.keys()) == set(
        chunk.keys()
    ), f"Keys mismatch: {set(restored.keys())} != {set(chunk.keys())}"

    # Should have the same values
    for key in chunk:
        assert (
            restored[key] == chunk[key]
        ), f"Value mismatch for key '{key}': {restored[key]} != {chunk[key]}"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_10_double_roundtrip_is_stable(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 10: StopChunkWithUsage round-trip**
    **Validates: Requirements 7.4**

    *For any* valid StopChunkWithUsage object, multiple round-trips should
    produce stable results.
    """
    # First round-trip
    plain1 = chunk.to_plain_dict()
    restored1 = StopChunkWithUsage.from_dict(plain1)

    # Second round-trip
    plain2 = restored1.to_plain_dict()
    restored2 = StopChunkWithUsage.from_dict(plain2)

    # The two plain dicts should be identical
    assert plain1 == plain2, "Double round-trip produced different dicts"

    # The two restored objects should have identical data
    assert dict(restored1) == dict(
        restored2
    ), "Double round-trip produced different StopChunkWithUsage objects"
