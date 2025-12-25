"""Tests for usage recalculation after content transformations."""

from __future__ import annotations

from src.core.domain.openrouter_usage import OpenRouterUsage
from src.core.utils.usage_recalculation import (
    extract_content_text,
    recalculate_usage_after_transformation,
    should_recalculate_usage,
)


def test_recalculate_usage_after_transformation():
    """Test that usage is recalculated correctly after content transformation."""
    original_usage = {
        "prompt_tokens": 100,
        "completion_tokens": 500,
        "total_tokens": 600,
    }
    original_content = "A" * 2000  # ~500 tokens
    transformed_content = "A" * 600  # ~150 tokens (70% reduction)

    result = recalculate_usage_after_transformation(
        original_usage, original_content, transformed_content
    )

    assert result is not None
    assert result.prompt_tokens == 100  # Preserved
    assert result.completion_tokens < 500  # Reduced
    assert result.total_tokens == result.prompt_tokens + result.completion_tokens


def test_recalculate_usage_no_transformation():
    """Test that usage is unchanged when content is not transformed."""
    original_usage = OpenRouterUsage(
        prompt_tokens=100,
        completion_tokens=500,
        total_tokens=600,
    )
    content = "Same content"

    result = recalculate_usage_after_transformation(original_usage, content, content)

    assert result == original_usage


def test_recalculate_usage_none_input():
    """Test that None is returned when no usage is provided."""
    result = recalculate_usage_after_transformation(None, "original", "transformed")

    assert result is None


def test_should_recalculate_usage_valid_response():
    """Test that recalculation is triggered for valid chat completion responses."""
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello, world!",
                }
            }
        ]
    }

    assert should_recalculate_usage(response) is True


def test_should_recalculate_usage_streaming_response():
    """Test that recalculation is triggered for streaming responses."""
    response = {
        "choices": [
            {
                "delta": {
                    "content": "Hello",
                }
            }
        ]
    }

    assert should_recalculate_usage(response) is True


def test_should_recalculate_usage_no_choices():
    """Test that recalculation is not triggered when no choices present."""
    response = {"id": "test", "object": "chat.completion"}

    assert should_recalculate_usage(response) is False


def test_should_recalculate_usage_non_dict():
    """Test that recalculation is not triggered for non-dict content."""
    assert should_recalculate_usage("string content") is False
    assert should_recalculate_usage(None) is False
    assert should_recalculate_usage([]) is False


def test_extract_content_text_from_message():
    """Test extracting text from message content."""
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Test message content",
                }
            }
        ]
    }

    result = extract_content_text(response)
    assert result == "Test message content"


def test_extract_content_text_from_delta():
    """Test extracting text from delta content."""
    response = {
        "choices": [
            {
                "delta": {
                    "content": "Streaming content",
                }
            }
        ]
    }

    result = extract_content_text(response)
    assert result == "Streaming content"


def test_extract_content_text_empty():
    """Test extracting text from empty response."""
    response = {"choices": []}

    result = extract_content_text(response)
    assert result == ""


def test_extract_content_text_no_content():
    """Test extracting text when no content field present."""
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                }
            }
        ]
    }

    result = extract_content_text(response)
    assert result == ""


def test_recalculate_usage_preserves_prompt_tokens():
    """Test that prompt tokens are always preserved during recalculation."""
    original_usage = {
        "prompt_tokens": 250,
        "completion_tokens": 1000,
        "total_tokens": 1250,
    }
    original_content = "X" * 4000
    transformed_content = "X" * 400  # 90% reduction

    result = recalculate_usage_after_transformation(
        original_usage, original_content, transformed_content
    )

    assert result is not None
    assert result.prompt_tokens == 250  # Must be preserved
    assert result.completion_tokens < 1000  # Should be reduced
    assert result.total_tokens == 250 + result.completion_tokens


def test_recalculate_usage_with_zero_original():
    """Test recalculation when original completion tokens is zero."""
    original_usage = {
        "prompt_tokens": 50,
        "completion_tokens": 0,
        "total_tokens": 50,
    }
    original_content = ""
    transformed_content = "New content added"

    result = recalculate_usage_after_transformation(
        original_usage, original_content, transformed_content
    )

    assert result is not None
    assert result.prompt_tokens == 50
    assert result.completion_tokens > 0  # Should now have tokens
    assert result.total_tokens == 50 + result.completion_tokens
