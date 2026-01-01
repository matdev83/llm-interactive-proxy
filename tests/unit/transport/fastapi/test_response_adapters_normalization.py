"""
Tests for response envelope normalization functions.

This module tests the normalization helpers and _normalize_response_envelope()
function to ensure usage and metadata are properly normalized to typed contracts.
"""

from __future__ import annotations

from typing import Any

from pydantic.types import JsonValue
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
)
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.transport.fastapi.response_adapters import (
    _normalize_metadata_to_json_safe,
    _normalize_response_envelope,
    _normalize_usage_to_summary,
)


class TestNormalizeUsageToSummary:
    """Tests for _normalize_usage_to_summary helper function."""

    def test_none_returns_none(self) -> None:
        """Test that None usage returns None."""
        result = _normalize_usage_to_summary(None)
        assert result is None

    def test_usage_summary_passes_through(self) -> None:
        """Test that UsageSummary instance passes through unchanged."""
        usage = UsageSummary(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        result = _normalize_usage_to_summary(usage)
        assert result is usage
        assert isinstance(result, UsageSummary)
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert result.total_tokens == 30

    def test_dict_converts_to_usage_summary(self) -> None:
        """Test that dict usage converts to UsageSummary."""
        usage_dict = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        result = _normalize_usage_to_summary(usage_dict)
        assert isinstance(result, UsageSummary)
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert result.total_tokens == 30

    def test_dict_with_extensions(self) -> None:
        """Test that dict with extensions converts correctly."""
        usage_dict = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "custom_field": "value",
        }
        result = _normalize_usage_to_summary(usage_dict)
        assert isinstance(result, UsageSummary)
        assert result.prompt_tokens == 10
        assert "custom_field" in result.extensions
        assert result.extensions["custom_field"] == "value"

    def test_empty_dict_returns_usage_summary(self) -> None:
        """Test that empty dict returns UsageSummary with None values."""
        result = _normalize_usage_to_summary({})
        assert isinstance(result, UsageSummary)
        assert result.prompt_tokens is None
        assert result.completion_tokens is None
        assert result.total_tokens is None


class TestNormalizeMetadataToJsonSafe:
    """Tests for _normalize_metadata_to_json_safe helper function."""

    def test_none_returns_none(self) -> None:
        """Test that None metadata returns None."""
        result = _normalize_metadata_to_json_safe(None)
        assert result is None

    def test_json_safe_dict_passes_through(self) -> None:
        """Test that dict[str, JsonValue] passes through (with sanitization)."""
        metadata: dict[str, JsonValue] = {"key1": "value1", "key2": 42, "key3": True}
        result = _normalize_metadata_to_json_safe(metadata)
        assert isinstance(result, dict)
        assert result["key1"] == "value1"
        assert result["key2"] == 42
        assert result["key3"] is True

    def test_dict_with_non_serializable_filtered(self) -> None:
        """Test that non-serializable values are filtered out."""

        # Create a dict with a non-serializable value (function)
        def non_serializable_func() -> None:
            pass

        metadata: dict[str, Any] = {
            "key1": "value1",
            "key2": 42,
            "non_serializable": non_serializable_func,
        }
        result = _normalize_metadata_to_json_safe(metadata)
        assert isinstance(result, dict)
        assert result["key1"] == "value1"
        assert result["key2"] == 42
        # Non-serializable value should be filtered out
        assert "non_serializable" not in result

    def test_empty_dict_returns_dict(self) -> None:
        """Test that empty dict returns empty dict."""
        result = _normalize_metadata_to_json_safe({})
        assert isinstance(result, dict)
        assert len(result) == 0


class TestNormalizeResponseEnvelope:
    """Tests for _normalize_response_envelope function."""

    def test_response_envelope_passes_through_with_normalization(self) -> None:
        """Test that ResponseEnvelope passes through with normalized usage/metadata."""
        usage = UsageSummary(prompt_tokens=10, completion_tokens=20)
        metadata: dict[str, JsonValue] = {"key": "value"}
        envelope = ResponseEnvelope(
            content={"test": "data"},
            usage=usage,
            metadata=metadata,
        )
        result = _normalize_response_envelope(envelope)
        assert isinstance(result, ResponseEnvelope)
        assert result.usage is usage  # Already typed, should pass through
        assert result.metadata == metadata

    def test_response_envelope_with_dict_usage_normalizes(self) -> None:
        """Test that ResponseEnvelope with dict usage gets normalized."""
        # This shouldn't happen in practice, but we test the normalization
        envelope = ResponseEnvelope(
            content={"test": "data"},
            usage={"prompt_tokens": 10},  # type: ignore[arg-type]
            metadata={"key": "value"},
        )
        result = _normalize_response_envelope(envelope)
        assert isinstance(result, ResponseEnvelope)
        assert isinstance(result.usage, UsageSummary)
        assert result.usage.prompt_tokens == 10

    def test_chat_response_converts_correctly(self) -> None:
        """Test that ChatResponse converts to ResponseEnvelope with normalized fields."""
        usage = UsageSummary(prompt_tokens=10, completion_tokens=20)
        chat_response = ChatResponse(
            id="test-id",
            created=1234567890,
            model="test-model",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content="test"
                    ),
                    finish_reason="stop",
                )
            ],
            usage=usage,
        )
        result = _normalize_response_envelope(chat_response)
        assert isinstance(result, ResponseEnvelope)
        assert isinstance(result.usage, UsageSummary)
        assert result.usage.prompt_tokens == 10
        assert result.metadata is not None
        assert result.metadata["model"] == "test-model"

    def test_chat_response_without_model(self) -> None:
        """Test ChatResponse conversion when model is None."""
        chat_response = ChatResponse(
            id="test-id",
            created=1234567890,
            model="",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content="test"
                    ),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )
        result = _normalize_response_envelope(chat_response)
        assert isinstance(result, ResponseEnvelope)
        assert result.usage is None
        assert result.metadata is None

    def test_processed_response_converts_correctly(self) -> None:
        """Test that ProcessedResponse converts to ResponseEnvelope with normalized fields."""
        usage = UsageSummary(prompt_tokens=10, completion_tokens=20)
        metadata: dict[str, JsonValue] = {"key": "value"}
        processed = ProcessedResponse(
            content={"test": "data"},
            usage=usage,
            metadata=metadata,
        )
        result = _normalize_response_envelope(processed)
        assert isinstance(result, ResponseEnvelope)
        assert isinstance(result.usage, UsageSummary)
        assert result.usage.prompt_tokens == 10
        assert result.metadata == metadata

    def test_dict_converts_with_usage_extraction(self) -> None:
        """Test that dict converts to ResponseEnvelope with usage extraction."""
        response_dict: dict[str, Any] = {
            "content": {"test": "data"},
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "metadata": {"key": "value"},
        }
        result = _normalize_response_envelope(
            response_dict
        )  # pyright: ignore[reportArgumentType]
        assert isinstance(result, ResponseEnvelope)
        assert isinstance(result.usage, UsageSummary)
        assert result.usage.prompt_tokens == 10
        assert result.metadata is not None
        assert result.metadata["key"] == "value"

    def test_dict_without_usage_or_metadata(self) -> None:
        """Test dict conversion when usage/metadata are not present."""
        response_dict: dict[str, Any] = {"content": {"test": "data"}}
        result = _normalize_response_envelope(
            response_dict
        )  # pyright: ignore[reportArgumentType]
        assert isinstance(result, ResponseEnvelope)
        assert result.usage is None
        assert result.metadata is None

    def test_dict_with_usage_in_content(self) -> None:
        """Test dict conversion when usage is nested in content."""
        response_dict: dict[str, Any] = {
            "choices": [{"message": {"content": "test"}}],
            "usage": {"prompt_tokens": 10},
        }
        result = _normalize_response_envelope(
            response_dict
        )  # pyright: ignore[reportArgumentType]
        assert isinstance(result, ResponseEnvelope)
        assert isinstance(result.usage, UsageSummary)
        assert result.usage.prompt_tokens == 10

    def test_other_type_with_usage_attribute(self) -> None:
        """Test conversion of other types with usage attribute."""

        class MockResponse:
            def __init__(self) -> None:
                self.usage = UsageSummary(prompt_tokens=10)
                self.metadata: dict[str, JsonValue] = {"key": "value"}

            def model_dump(self) -> dict[str, Any]:
                return {"test": "data"}

        mock_response = MockResponse()
        result = _normalize_response_envelope(
            mock_response
        )  # pyright: ignore[reportArgumentType]
        assert isinstance(result, ResponseEnvelope)
        assert isinstance(result.usage, UsageSummary)
        assert result.usage.prompt_tokens == 10
        assert result.metadata == {"key": "value"}

    def test_other_type_with_dict_usage_normalizes(self) -> None:
        """Test conversion of other types with dict usage gets normalized."""

        class MockResponse:
            def __init__(self) -> None:
                self.usage = {"prompt_tokens": 10}  # type: ignore[assignment]
                self.metadata = {"key": "value"}

            def model_dump(self) -> dict[str, Any]:
                return {"test": "data"}

        mock_response = MockResponse()
        result = _normalize_response_envelope(
            mock_response
        )  # pyright: ignore[reportArgumentType]
        assert isinstance(result, ResponseEnvelope)
        assert isinstance(result.usage, UsageSummary)
        assert result.usage.prompt_tokens == 10

    def test_string_fallback(self) -> None:
        """Test that string fallback works correctly."""
        result = _normalize_response_envelope(
            "test string"
        )  # pyright: ignore[reportArgumentType]
        assert isinstance(result, ResponseEnvelope)
        assert result.content == "test string"
        assert result.usage is None
        assert result.metadata is None
