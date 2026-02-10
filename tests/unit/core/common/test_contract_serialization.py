"""Unit tests for canonical contract serialization utilities.

Tests deterministic serialization and secret-safe logging for canonical contracts.
"""

from __future__ import annotations

import json

from src.core.common.contract_serialization import (
    serialize_dict_for_capture,
    serialize_for_capture,
    serialize_for_logging,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.usage_canonical_record import (
    CanonicalUsageRecord,
    UsageCompletionOutcome,
)
from src.core.domain.usage_summary import UsageSummary


class TestSerializeForCapture:
    """Tests for serialize_for_capture() - deterministic serialization for capture."""

    def test_serialize_for_capture_deterministic(self) -> None:
        """Same contract produces identical bytes."""
        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        result1 = serialize_for_capture(request)
        result2 = serialize_for_capture(request)

        assert result1 == result2
        assert isinstance(result1, bytes)
        assert isinstance(result2, bytes)

    def test_serialize_for_capture_pydantic_models(self) -> None:
        """Handles Pydantic models deterministically."""
        # Test RequestContext (requires headers, cookies, state, app_state)
        from src.core.domain.request_context import RequestCookies, RequestHeaders

        context = RequestContext(
            headers=RequestHeaders(),
            cookies=RequestCookies(),
            state={},
            app_state={},
            request_id="test-123",
            session_id="session-456",
            domain_request=CanonicalChatRequest(
                model="gpt-4", messages=[ChatMessage(role="user", content="test")]
            ),
        )
        result = serialize_for_capture(context)
        assert isinstance(result, bytes)
        assert len(result) > 0

        # Test UsageSummary
        usage = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={"custom": "value"},
        )
        result = serialize_for_capture(usage)
        assert isinstance(result, bytes)
        assert len(result) > 0

        # Test CanonicalChatRequest
        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            temperature=0.7,
        )
        result = serialize_for_capture(request)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_serialize_for_capture_dict_list(self) -> None:
        """Handles dict/list types deterministically."""
        # Test dict
        data = {"z": 3, "a": 1, "m": 2}
        result = serialize_for_capture(data)
        assert isinstance(result, bytes)

        # Verify keys are sorted (deterministic)
        decoded = json.loads(result.decode("utf-8"))
        assert list(decoded.keys()) == ["a", "m", "z"]

        # Test list (order preserved)
        data_list = [3, 1, 2]
        result = serialize_for_capture(data_list)
        assert isinstance(result, bytes)
        decoded = json.loads(result.decode("utf-8"))
        assert decoded == [3, 1, 2]  # Order preserved

    def test_serialize_for_capture_bytes(self) -> None:
        """Bytes are kept as-is."""
        data = b"raw bytes"
        result = serialize_for_capture(data)
        assert result == data

    def test_serialize_for_capture_string(self) -> None:
        """Strings are encoded to bytes."""
        data = "test string"
        result = serialize_for_capture(data)
        assert result == b"test string"

    def test_serialize_for_capture_nested_structures(self) -> None:
        """Nested structures are serialized deterministically."""
        data = {
            "z": {"c": 3, "a": 1, "b": 2},
            "a": [3, 1, 2],
            "m": "value",
        }
        result1 = serialize_for_capture(data)
        result2 = serialize_for_capture(data)

        assert result1 == result2

        # Verify nested dict keys are sorted
        decoded = json.loads(result1.decode("utf-8"))
        assert list(decoded.keys()) == ["a", "m", "z"]
        assert list(decoded["z"].keys()) == ["a", "b", "c"]

    def test_serialize_for_capture_dict_with_nested_domain_model(self) -> None:
        """Nested domain models inside dict payloads are JSON-serialized safely."""
        usage = CanonicalUsageRecord(
            provider_id="gemini",
            prompt_tokens=10,
            completion_tokens=5,
            completion_outcome=UsageCompletionOutcome.complete,
        )
        payload = {
            "content": {"text": "ok"},
            "canonical_usage": usage,
        }

        result = serialize_for_capture(payload)
        decoded = json.loads(result.decode("utf-8"))

        assert decoded["canonical_usage"]["provider_id"] == "gemini"
        assert decoded["canonical_usage"]["prompt_tokens"] == 10
        assert decoded["canonical_usage"]["completion_tokens"] == 5
        assert decoded["canonical_usage"]["completion_outcome"] == "complete"


class TestSerializeForLogging:
    """Tests for serialize_for_logging() - secret-safe logging serialization."""

    def test_serialize_for_logging_redacts_secrets(self) -> None:
        """Verifies redaction of DEFAULT_REDACTED_FIELDS."""
        data = {
            "api_key": "sk-test123456789",
            "password": "secret123",
            "normal_field": "value",
        }

        result = serialize_for_logging(data, redact=True)
        assert isinstance(result, str)

        # Parse JSON and verify redaction
        # Note: redact() preserves first 2 and last 2 chars for strings > 6 chars
        parsed = json.loads(result)
        assert parsed["api_key"] == "sk***89"  # First 2 + mask + last 2
        assert parsed["password"] == "se***23"  # First 2 + mask + last 2
        assert parsed["normal_field"] == "value"

    def test_serialize_for_logging_preserves_non_sensitive(self) -> None:
        """Non-sensitive fields are preserved."""
        data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
        }

        result = serialize_for_logging(data, redact=True)
        parsed = json.loads(result)

        assert parsed["model"] == "gpt-4"
        assert parsed["messages"] == [{"role": "user", "content": "Hello"}]
        assert parsed["temperature"] == 0.7

    def test_serialize_for_logging_nested_redaction(self) -> None:
        """Redaction works in nested structures."""
        data = {
            "request": {
                "api_key": "sk-test123",
                "model": "gpt-4",
            },
            "headers": {
                "authorization": "Bearer token123",
                "content-type": "application/json",
            },
        }

        result = serialize_for_logging(data, redact=True)
        parsed = json.loads(result)

        # Note: redact() preserves first 2 and last 2 chars for strings > 6 chars
        assert parsed["request"]["api_key"] == "sk***23"  # First 2 + mask + last 2
        assert parsed["request"]["model"] == "gpt-4"
        assert (
            parsed["headers"]["authorization"] == "Be***23"
        )  # First 2 + mask + last 2
        assert parsed["headers"]["content-type"] == "application/json"

    def test_serialize_for_logging_deterministic(self) -> None:
        """Same input produces identical output (even with redaction)."""
        data = {
            "api_key": "sk-test123",
            "model": "gpt-4",
            "z": 3,
            "a": 1,
        }

        result1 = serialize_for_logging(data, redact=True)
        result2 = serialize_for_logging(data, redact=True)

        assert result1 == result2

        # Verify keys are sorted
        parsed = json.loads(result1)
        assert list(parsed.keys()) == ["a", "api_key", "model", "z"]

    def test_serialize_for_logging_no_redaction(self) -> None:
        """Redaction can be disabled."""
        data = {"api_key": "sk-test123", "password": "secret"}

        result = serialize_for_logging(data, redact=False)
        parsed = json.loads(result)

        assert parsed["api_key"] == "sk-test123"
        assert parsed["password"] == "secret"

    def test_serialize_for_logging_pydantic_models(self) -> None:
        """Handles Pydantic models with redaction."""
        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        # Add a sensitive field via extra_body (if supported)
        # For now, test that it serializes correctly
        result = serialize_for_logging(request, redact=True)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["model"] == "gpt-4"

    def test_serialize_for_logging_list_with_dicts(self) -> None:
        """Redaction works in lists containing dicts."""
        data = {
            "items": [
                {"api_key": "sk-test1", "name": "item1"},
                {"password": "secret", "name": "item2"},
            ],
        }

        result = serialize_for_logging(data, redact=True)
        parsed = json.loads(result)

        # Note: redact() preserves first 2 and last 2 chars for strings > 6 chars
        # "sk-test1" is 8 chars, so "sk***t1"
        assert parsed["items"][0]["api_key"] == "sk***t1"  # First 2 + mask + last 2
        assert parsed["items"][0]["name"] == "item1"
        # "secret" is 6 chars, so full mask
        assert parsed["items"][1]["password"] == "***"  # <= 6 chars, full mask
        assert parsed["items"][1]["name"] == "item2"

    def test_serialize_for_logging_list_contract_redaction(self) -> None:
        """Redaction works when contract itself is a list of dicts."""
        # Test when the contract is a list (not a dict containing a list)
        data = [
            {"api_key": "sk-test123456", "name": "item1"},
            {"password": "secret123", "name": "item2"},
            {"normal": "value"},  # No secrets
        ]

        result = serialize_for_logging(data, redact=True)
        parsed = json.loads(result)

        # Should be a list with redacted dicts
        assert isinstance(parsed, list)
        assert len(parsed) == 3

        # First item: api_key should be redacted
        assert parsed[0]["api_key"] == "sk***56"  # First 2 + mask + last 2
        assert parsed[0]["name"] == "item1"

        # Second item: password should be redacted
        assert parsed[1]["password"] == "se***23"  # First 2 + mask + last 2
        assert parsed[1]["name"] == "item2"

        # Third item: no secrets, should be preserved
        assert parsed[2]["normal"] == "value"

    def test_serialize_for_logging_deeply_nested_list_redaction(self) -> None:
        """Redaction works for deeply nested lists (lists containing lists containing dicts)."""
        # Test deeply nested structure: list -> list -> dict
        data = [
            [
                {"api_key": "sk-test123456", "name": "nested1"},
                {"password": "secret123", "name": "nested2"},
            ],
            [
                {"authorization": "Bearer abc123def456", "name": "nested3"},
                {"normal": "value"},  # No secrets
            ],
        ]

        result = serialize_for_logging(data, redact=True)
        parsed = json.loads(result)

        # Should be a list of lists
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert isinstance(parsed[0], list)
        assert isinstance(parsed[1], list)

        # First nested list: first dict should have redacted api_key
        assert parsed[0][0]["api_key"] == "sk***56"  # First 2 + mask + last 2
        assert parsed[0][0]["name"] == "nested1"

        # First nested list: second dict should have redacted password
        assert parsed[0][1]["password"] == "se***23"  # First 2 + mask + last 2
        assert parsed[0][1]["name"] == "nested2"

        # Second nested list: first dict should have redacted authorization
        # "Bearer abc123def456" is 20 chars, so "Be***56" (first 2 + mask + last 2)
        assert parsed[1][0]["authorization"] == "Be***56"  # First 2 + mask + last 2
        assert parsed[1][0]["name"] == "nested3"

        # Second nested list: second dict has no secrets
        assert parsed[1][1]["normal"] == "value"


class TestSerializeDictForCapture:
    """Tests for serialize_dict_for_capture() - helper for dict serialization."""

    def test_serialize_dict_for_capture_sorted_keys(self) -> None:
        """Dict keys are sorted deterministically."""
        data = {"z": 3, "a": 1, "m": 2}

        result1 = serialize_dict_for_capture(data)
        result2 = serialize_dict_for_capture(data)

        assert result1 == result2
        assert isinstance(result1, bytes)

        # Verify keys are sorted
        decoded = json.loads(result1.decode("utf-8"))
        assert list(decoded.keys()) == ["a", "m", "z"]

    def test_serialize_dict_for_capture_nested(self) -> None:
        """Nested dicts have sorted keys."""
        data = {
            "z": {"c": 3, "a": 1},
            "a": {"b": 2},
        }

        result = serialize_dict_for_capture(data)
        decoded = json.loads(result.decode("utf-8"))

        assert list(decoded.keys()) == ["a", "z"]
        assert list(decoded["z"].keys()) == ["a", "c"]
        assert list(decoded["a"].keys()) == ["b"]

    def test_serialize_dict_for_capture_empty(self) -> None:
        """Empty dict serializes correctly."""
        result = serialize_dict_for_capture({})
        assert result == b"{}"

    def test_serialize_dict_for_capture_compact_format(self) -> None:
        """Uses compact format (no spaces)."""
        data = {"a": 1, "b": 2}
        result = serialize_dict_for_capture(data)
        decoded_str = result.decode("utf-8")

        # Compact format: no spaces after colons/commas
        assert " " not in decoded_str
        assert decoded_str == '{"a":1,"b":2}'
