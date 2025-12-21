"""Tests for canonical usage record models.

This module tests the CanonicalUsageRecord, UsageCompletionOutcome,
UsageIncompleteReason enums, and UsagePayload models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic.types import JsonValue
from src.core.domain.usage_canonical_record import (
    CanonicalUsageRecord,
    UsageCompletionOutcome,
    UsageIncompleteReason,
)
from src.core.domain.usage_payload import UsagePayload


class TestUsageCompletionOutcome:
    """Test UsageCompletionOutcome enum."""

    def test_enum_values(self) -> None:
        """Test that enum has correct values."""
        assert UsageCompletionOutcome.complete == "complete"
        assert UsageCompletionOutcome.incomplete == "incomplete"

    def test_enum_membership(self) -> None:
        """Test enum membership."""
        assert UsageCompletionOutcome.complete in UsageCompletionOutcome
        assert UsageCompletionOutcome.incomplete in UsageCompletionOutcome


class TestUsageIncompleteReason:
    """Test UsageIncompleteReason enum."""

    def test_enum_values(self) -> None:
        """Test that enum has correct values."""
        assert UsageIncompleteReason.client_disconnect == "client_disconnect"
        assert UsageIncompleteReason.backend_error == "backend_error"
        assert UsageIncompleteReason.timeout == "timeout"
        assert UsageIncompleteReason.upstream_cancelled == "upstream_cancelled"
        assert UsageIncompleteReason.unknown == "unknown"

    def test_enum_membership(self) -> None:
        """Test enum membership."""
        assert UsageIncompleteReason.client_disconnect in UsageIncompleteReason
        assert UsageIncompleteReason.backend_error in UsageIncompleteReason
        assert UsageIncompleteReason.timeout in UsageIncompleteReason
        assert UsageIncompleteReason.upstream_cancelled in UsageIncompleteReason
        assert UsageIncompleteReason.unknown in UsageIncompleteReason


class TestCanonicalUsageRecord:
    """Test CanonicalUsageRecord model."""

    def test_create_with_all_fields(self) -> None:
        """Test creating CanonicalUsageRecord with all fields."""
        record = CanonicalUsageRecord(
            provider_id="openai",
            model_id="gpt-4",
            request_id="req-123",
            protocol="openai",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost=0.002,
            completion_outcome=UsageCompletionOutcome.complete,
            incomplete_reason=None,
            extensions={"requests": 1},
        )
        assert record.provider_id == "openai"
        assert record.model_id == "gpt-4"
        assert record.request_id == "req-123"
        assert record.protocol == "openai"
        assert record.prompt_tokens == 100
        assert record.completion_tokens == 50
        assert record.total_tokens == 150
        assert record.cost == 0.002
        assert record.completion_outcome == UsageCompletionOutcome.complete
        assert record.incomplete_reason is None
        assert record.extensions == {"requests": 1}

    def test_create_with_none_fields(self) -> None:
        """Test creating CanonicalUsageRecord with None fields."""
        record = CanonicalUsageRecord()
        assert record.provider_id is None
        assert record.model_id is None
        assert record.request_id is None
        assert record.protocol is None
        assert record.prompt_tokens is None
        assert record.completion_tokens is None
        assert record.total_tokens is None
        assert record.cost is None
        assert record.completion_outcome is None
        assert record.incomplete_reason is None
        assert record.extensions == {}

    def test_extensions_defaults_to_empty_dict(self) -> None:
        """Test that extensions defaults to empty dict."""
        record = CanonicalUsageRecord()
        assert record.extensions == {}
        assert isinstance(record.extensions, dict)

    def test_total_tokens_derived_when_both_available(self) -> None:
        """Test that total_tokens is derived when both prompt and completion are available."""
        record = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert record.total_tokens == 150

    def test_total_tokens_none_when_prompt_missing(self) -> None:
        """Test that total_tokens is None when prompt_tokens is missing."""
        record = CanonicalUsageRecord(
            completion_tokens=50,
        )
        assert record.total_tokens is None

    def test_total_tokens_none_when_completion_missing(self) -> None:
        """Test that total_tokens is None when completion_tokens is missing."""
        record = CanonicalUsageRecord(
            prompt_tokens=100,
        )
        assert record.total_tokens is None

    def test_total_tokens_explicit_override(self) -> None:
        """Test that explicit total_tokens can override derived value."""
        record = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=200,  # Explicit override
        )
        assert record.total_tokens == 200

    def test_incomplete_reason_only_when_incomplete(self) -> None:
        """Test incomplete_reason can be set when completion_outcome is incomplete."""
        record = CanonicalUsageRecord(
            completion_outcome=UsageCompletionOutcome.incomplete,
            incomplete_reason=UsageIncompleteReason.client_disconnect,
        )
        assert record.completion_outcome == UsageCompletionOutcome.incomplete
        assert record.incomplete_reason == UsageIncompleteReason.client_disconnect

    def test_incomplete_reason_validation_error_when_complete(self) -> None:
        """Test that incomplete_reason raises ValidationError when completion_outcome is complete."""
        with pytest.raises(ValidationError) as exc_info:
            CanonicalUsageRecord(
                completion_outcome=UsageCompletionOutcome.complete,
                incomplete_reason=UsageIncompleteReason.client_disconnect,
            )
        assert (
            "incomplete_reason can only be set when completion_outcome is incomplete"
            in str(exc_info.value)
        )

    def test_incomplete_reason_none_when_complete_allowed(self) -> None:
        """Test that incomplete_reason can be None when completion_outcome is complete."""
        record = CanonicalUsageRecord(
            completion_outcome=UsageCompletionOutcome.complete,
            incomplete_reason=None,
        )
        assert record.completion_outcome == UsageCompletionOutcome.complete
        assert record.incomplete_reason is None

    def test_extensions_preservation(self) -> None:
        """Test that extensions container preserves provider-specific data."""
        extensions: dict[str, JsonValue] = {
            "cost": 0.002,
            "requests": 1,
            "provider": "openai",
            "enabled": True,
            "optional": None,
        }
        record = CanonicalUsageRecord(extensions=extensions)
        assert record.extensions == extensions
        assert record.extensions["cost"] == 0.002
        assert record.extensions["requests"] == 1

    def test_json_serialization(self) -> None:
        """Test that CanonicalUsageRecord can be serialized to JSON."""
        record = CanonicalUsageRecord(
            provider_id="openai",
            model_id="gpt-4",
            request_id="req-123",
            protocol="openai",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost=0.002,
            completion_outcome=UsageCompletionOutcome.complete,
            extensions={"requests": 1},
        )
        data = record.model_dump()
        assert data["provider_id"] == "openai"
        assert data["model_id"] == "gpt-4"
        assert data["request_id"] == "req-123"
        assert data["protocol"] == "openai"
        assert data["prompt_tokens"] == 100
        assert data["completion_tokens"] == 50
        assert data["total_tokens"] == 150
        assert data["cost"] == 0.002
        assert data["completion_outcome"] == "complete"
        assert data["extensions"] == {"requests": 1}


class TestUsagePayload:
    """Test UsagePayload model."""

    def test_create_with_payload(self) -> None:
        """Test creating UsagePayload with payload dict."""
        payload_data: dict[str, JsonValue] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        usage_payload = UsagePayload(payload=payload_data)
        assert usage_payload.payload == payload_data

    def test_payload_accepts_json_value_types(self) -> None:
        """Test that payload accepts various JsonValue types."""
        payload_data: dict[str, JsonValue] = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }
        usage_payload = UsagePayload(payload=payload_data)
        assert usage_payload.payload == payload_data

    def test_json_serialization(self) -> None:
        """Test that UsagePayload can be serialized."""
        payload_data: dict[str, JsonValue] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        usage_payload = UsagePayload(payload=payload_data)
        data = usage_payload.model_dump()
        assert data["payload"] == payload_data
