"""
Property-based tests for usage data preservation in streaming pipeline.

This module contains property tests for:
- Property 1: Usage data preservation (Requirements 1.1, 4.1, 4.4, 6.4)

These tests verify that usage data flows correctly through the streaming pipeline
and is serialized at the top level of SSE chunks, not embedded in delta.content.
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.ports.streaming_contracts import (
    StopChunkWithUsage,
    StreamingContent,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating usage data and stop chunks
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
def stop_chunk_with_usage_dict_strategy(draw: Any) -> dict[str, Any]:
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
    chunk_dict = draw(stop_chunk_with_usage_dict_strategy())
    return StopChunkWithUsage(chunk_dict)


@st.composite
def streaming_content_with_stop_chunk_strategy(draw: Any) -> StreamingContent:
    """Generate StreamingContent with StopChunkWithUsage as content."""
    stop_chunk = draw(stop_chunk_with_usage_strategy())
    metadata = {
        "provider": draw(
            st.sampled_from(["openai", "anthropic", "gemini", "test", "mock"])
        ),
    }
    # Optionally add stream_id
    if draw(st.booleans()):
        metadata["stream_id"] = draw(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
                min_size=1,
                max_size=50,
            )
        )

    return StreamingContent(
        content=stop_chunk,
        metadata=metadata,
        is_done=False,  # is_done is False because the StopChunkWithUsage check happens first
    )


# ============================================================================
# Property 1: Usage data preservation
# ============================================================================


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_1_usage_at_top_level_in_sse_output(
    chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 1: Usage data preservation**
    **Validates: Requirements 1.1, 4.1, 4.4, 6.4**

    Property 1: Usage data preservation

    *For any* stop chunk with usage data flowing through the streaming pipeline,
    the final SSE output SHALL contain the usage data as a top-level field
    (not embedded in delta.content).
    """
    # Create StreamingContent with StopChunkWithUsage as content
    streaming_content = StreamingContent(
        content=chunk,
        metadata={"provider": "test"},
    )

    # Convert to bytes (SSE format)
    sse_bytes = streaming_content.to_bytes()
    sse_str = sse_bytes.decode("utf-8")

    # Parse the SSE output
    # Format should be: "data: {...}\n\ndata: [DONE]\n\n"
    lines = [line for line in sse_str.split("\n") if line.startswith("data: ")]
    assert len(lines) >= 1, f"Expected at least one data line, got: {sse_str}"

    # First data line should be the JSON chunk
    first_data = lines[0][6:]  # Remove "data: " prefix
    if first_data != "[DONE]":
        parsed = json.loads(first_data)

        # Usage MUST be at top level
        assert "usage" in parsed, (
            f"Usage data must be at top level of SSE chunk. "
            f"Got keys: {list(parsed.keys())}"
        )

        # Usage must be a dict with the expected fields
        usage = parsed["usage"]
        assert isinstance(usage, dict), f"Usage must be a dict, got {type(usage)}"
        assert "prompt_tokens" in usage, "Usage must have prompt_tokens"
        assert "completion_tokens" in usage, "Usage must have completion_tokens"
        assert "total_tokens" in usage, "Usage must have total_tokens"

        # Usage values must match the original
        original_usage = chunk["usage"]
        assert usage["prompt_tokens"] == original_usage["prompt_tokens"], (
            f"prompt_tokens mismatch: {usage['prompt_tokens']} != "
            f"{original_usage['prompt_tokens']}"
        )
        assert usage["completion_tokens"] == original_usage["completion_tokens"], (
            f"completion_tokens mismatch: {usage['completion_tokens']} != "
            f"{original_usage['completion_tokens']}"
        )
        assert usage["total_tokens"] == original_usage["total_tokens"], (
            f"total_tokens mismatch: {usage['total_tokens']} != "
            f"{original_usage['total_tokens']}"
        )


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_1_usage_not_in_delta_content(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 1: Usage data preservation**
    **Validates: Requirements 1.1, 4.1**

    *For any* stop chunk with usage data, the SSE output SHALL NOT contain
    the usage data embedded in delta.content (which would cause the usage
    data leak bug).
    """
    # Create StreamingContent with StopChunkWithUsage as content
    streaming_content = StreamingContent(
        content=chunk,
        metadata={"provider": "test"},
    )

    # Convert to bytes (SSE format)
    sse_bytes = streaming_content.to_bytes()
    sse_str = sse_bytes.decode("utf-8")

    # Parse the SSE output
    lines = [line for line in sse_str.split("\n") if line.startswith("data: ")]
    assert len(lines) >= 1, f"Expected at least one data line, got: {sse_str}"

    # First data line should be the JSON chunk
    first_data = lines[0][6:]  # Remove "data: " prefix
    if first_data != "[DONE]":
        parsed = json.loads(first_data)

        # Check that usage is NOT embedded in delta.content
        choices = parsed.get("choices", [])
        for choice in choices:
            delta = choice.get("delta", {})
            content = delta.get("content", "")

            # If content is a string, it should NOT contain the usage JSON
            if isinstance(content, str) and content:
                # Check that the content doesn't contain usage data as JSON
                assert (
                    '"usage"' not in content or '"prompt_tokens"' not in content
                ), f"Usage data appears to be embedded in delta.content: {content[:200]}"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_1_usage_dict_type_preserved(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 1: Usage data preservation**
    **Validates: Requirements 4.4, 6.4**

    *For any* stop chunk with usage data, the usage dict SHALL remain as a
    dict type throughout the pipeline (not converted to a string).
    """
    # Create StreamingContent with StopChunkWithUsage as content
    streaming_content = StreamingContent(
        content=chunk,
        metadata={"provider": "test"},
    )

    # Convert to bytes (SSE format)
    sse_bytes = streaming_content.to_bytes()
    sse_str = sse_bytes.decode("utf-8")

    # Parse the SSE output
    lines = [line for line in sse_str.split("\n") if line.startswith("data: ")]
    first_data = lines[0][6:]  # Remove "data: " prefix

    if first_data != "[DONE]":
        parsed = json.loads(first_data)

        # Usage must be a dict, not a string
        usage = parsed.get("usage")
        assert usage is not None, "Usage must be present in parsed output"
        assert isinstance(
            usage, dict
        ), f"Usage must be a dict after parsing, got {type(usage).__name__}: {usage}"


@given(content=streaming_content_with_stop_chunk_strategy())
@property_test_settings()
def test_property_1_streaming_content_with_stop_chunk_preserves_usage(
    content: StreamingContent,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 1: Usage data preservation**
    **Validates: Requirements 1.1, 4.1, 4.4, 6.4**

    *For any* StreamingContent with StopChunkWithUsage as content, the to_bytes()
    method SHALL emit the usage data at the top level of the SSE chunk.
    """
    # Get the original usage from the StopChunkWithUsage content
    assert isinstance(content.content, StopChunkWithUsage)
    original_usage = content.content["usage"]

    # Convert to bytes
    sse_bytes = content.to_bytes()
    sse_str = sse_bytes.decode("utf-8")

    # Parse the SSE output
    lines = [line for line in sse_str.split("\n") if line.startswith("data: ")]
    assert len(lines) >= 1, f"Expected at least one data line, got: {sse_str}"

    first_data = lines[0][6:]  # Remove "data: " prefix
    if first_data != "[DONE]":
        parsed = json.loads(first_data)

        # Usage must be at top level and match original
        assert "usage" in parsed, "Usage must be at top level"
        assert (
            parsed["usage"] == original_usage
        ), f"Usage mismatch: {parsed['usage']} != {original_usage}"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_1_sse_output_ends_with_done_marker(
    chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 1: Usage data preservation**
    **Validates: Requirements 1.1**

    *For any* stop chunk with usage data, the SSE output SHALL end with
    the [DONE] marker.
    """
    # Create StreamingContent with StopChunkWithUsage as content
    streaming_content = StreamingContent(
        content=chunk,
        metadata={"provider": "test"},
    )

    # Convert to bytes (SSE format)
    sse_bytes = streaming_content.to_bytes()
    sse_str = sse_bytes.decode("utf-8")

    # Should end with [DONE] marker
    assert (
        "data: [DONE]" in sse_str
    ), f"SSE output must contain [DONE] marker. Got: {sse_str}"
    assert sse_str.strip().endswith(
        "[DONE]"
    ), f"SSE output must end with [DONE] marker. Got: {sse_str}"


@given(chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
def test_property_1_all_chunk_fields_preserved(chunk: StopChunkWithUsage) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 1: Usage data preservation**
    **Validates: Requirements 1.1, 4.1**

    *For any* stop chunk with usage data, all fields (id, object, created,
    model, choices, usage) SHALL be preserved in the SSE output.
    """
    # Create StreamingContent with StopChunkWithUsage as content
    streaming_content = StreamingContent(
        content=chunk,
        metadata={"provider": "test"},
    )

    # Convert to bytes (SSE format)
    sse_bytes = streaming_content.to_bytes()
    sse_str = sse_bytes.decode("utf-8")

    # Parse the SSE output
    lines = [line for line in sse_str.split("\n") if line.startswith("data: ")]
    first_data = lines[0][6:]  # Remove "data: " prefix

    if first_data != "[DONE]":
        parsed = json.loads(first_data)

        # All original fields must be preserved
        for key in ["id", "object", "created", "model", "choices", "usage"]:
            assert key in parsed, f"Field '{key}' must be preserved in SSE output"
            assert (
                parsed[key] == chunk[key]
            ), f"Field '{key}' mismatch: {parsed[key]} != {chunk[key]}"
