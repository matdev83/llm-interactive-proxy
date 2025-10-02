"""
Tests for RateLimitRegistry (legacy rate limiting).

This module tests the legacy rate limiting functionality in rate_limit.py.
"""

import time

import pytest
from src.rate_limit import (
    RateLimitRegistry,
    _as_dict,
    _find_retry_delay_in_details,
    parse_retry_delay,
)


class TestRateLimitRegistry:
    """Tests for RateLimitRegistry class."""

    @pytest.fixture
    def registry(self) -> RateLimitRegistry:
        """Create a fresh RateLimitRegistry for each test."""
        return RateLimitRegistry()

    def test_initialization(self, registry: RateLimitRegistry) -> None:
        """Test registry initialization."""
        assert registry._until == {}

    def test_set_and_get_single_entry(self, registry: RateLimitRegistry) -> None:
        """Test setting and getting a single entry."""
        backend, model, key = "openai", "gpt-4", "user1"

        # Initially should return None
        assert registry.get(backend, model, key) is None

        # Set a delay
        registry.set(backend, model, key, 30.0)

        # Should now return the delay
        result = registry.get(backend, model, key)
        assert result is not None
        assert abs(result - time.time() - 30.0) < 1.0  # Allow small timing differences

    def test_set_with_none_model(self, registry: RateLimitRegistry) -> None:
        """Test setting with None model."""
        backend, key = "anthropic", "user2"

        registry.set(backend, None, key, 60.0)

        result = registry.get(backend, None, key)
        assert result is not None
        assert abs(result - time.time() - 60.0) < 1.0

    def test_get_nonexistent_entry(self, registry: RateLimitRegistry) -> None:
        """Test getting a nonexistent entry."""
        result = registry.get("nonexistent", "model", "key")
        assert result is None

    def test_entry_expiration(self, registry: RateLimitRegistry) -> None:
        """Test that entries expire and are cleaned up."""
        backend, model, key = "openai", "gpt-4", "user1"

        # Set a very short delay
        registry.set(backend, model, key, 0.1)

        # Should return the delay initially
        result = registry.get(backend, model, key)
        assert result is not None

        # Wait for expiration
        time.sleep(0.2)

        # Should return None and clean up the entry
        result = registry.get(backend, model, key)
        assert result is None

    def test_earliest_with_no_entries(self, registry: RateLimitRegistry) -> None:
        """Test earliest with no entries."""
        result = registry.earliest()
        assert result is None

    def test_earliest_with_single_entry(self, registry: RateLimitRegistry) -> None:
        """Test earliest with a single entry."""
        registry.set("backend1", "model1", "key1", 30.0)

        result = registry.earliest()
        assert result is not None
        assert abs(result - time.time() - 30.0) < 1.0

    def test_earliest_with_multiple_entries(self, registry: RateLimitRegistry) -> None:
        """Test earliest with multiple entries."""
        # Set different delays
        registry.set("backend1", "model1", "key1", 60.0)  # Later
        registry.set("backend2", "model2", "key2", 30.0)  # Earlier
        registry.set("backend3", "model3", "key3", 45.0)  # Middle

        result = registry.earliest()
        assert result is not None
        assert abs(result - time.time() - 30.0) < 1.0  # Should return the earliest

    def test_earliest_prunes_expired_entries(
        self, registry: RateLimitRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Expired entries should not affect earliest calculations."""

        current_time = {"value": 0.0}

        def fake_time() -> float:
            return current_time["value"]

        import time

        monkeypatch.setattr(time, "time", fake_time)

        registry.set("backend1", "model1", "key1", 5.0)
        registry.set("backend2", "model2", "key2", 2.0)

        # Advance time past the second entry's expiry without reading it via get()
        current_time["value"] = 3.0

        result = registry.earliest()
        assert result == pytest.approx(5.0)
        # The expired entry should be removed as part of the lookup
        assert ("backend2", "model2", "key2") not in registry._until

    def test_earliest_with_filtered_combinations(
        self, registry: RateLimitRegistry
    ) -> None:
        """Test earliest with filtered combinations."""
        # Set entries for different backends
        registry.set("backend1", "model1", "key1", 30.0)
        registry.set("backend2", "model2", "key2", 60.0)

        # Filter to only backend1
        combos = [("backend1", "model1", "key1")]
        result = registry.earliest(combos)

        assert result is not None
        assert abs(result - time.time() - 30.0) < 1.0

    def test_earliest_with_empty_combinations(
        self, registry: RateLimitRegistry
    ) -> None:
        """Test earliest with empty combinations list."""
        registry.set("backend1", "model1", "key1", 30.0)

        result = registry.earliest([])
        # Empty combinations list falls back to all entries
        assert result is not None
        assert abs(result - time.time() - 30.0) < 1.0

    def test_earliest_with_nonexistent_combinations(
        self, registry: RateLimitRegistry
    ) -> None:
        """Test earliest with nonexistent combinations."""
        registry.set("backend1", "model1", "key1", 30.0)

        combos = [("nonexistent", "model", "key")]
        result = registry.earliest(combos)
        assert result is None

    def test_multiple_keys_same_backend_model(
        self, registry: RateLimitRegistry
    ) -> None:
        """Test multiple keys for the same backend and model."""
        backend, model = "openai", "gpt-4"

        registry.set(backend, model, "key1", 30.0)
        registry.set(backend, model, "key2", 60.0)

        # Both should be retrievable
        result1 = registry.get(backend, model, "key1")
        result2 = registry.get(backend, model, "key2")

        assert result1 is not None
        assert result2 is not None
        assert result1 != result2  # Different timestamps

    def test_key_formatting_consistency(self, registry: RateLimitRegistry) -> None:
        """Test that key formatting is consistent."""
        backend, model, key = "openai", "gpt-4", "user1"

        registry.set(backend, model, key, 30.0)

        # Should work with exact same parameters
        result = registry.get(backend, model, key)
        assert result is not None

    def test_overwrite_existing_entry(self, registry: RateLimitRegistry) -> None:
        """Test overwriting an existing entry."""
        backend, model, key = "openai", "gpt-4", "user1"

        # Set initial delay
        registry.set(backend, model, key, 30.0)
        initial_result = registry.get(backend, model, key)
        assert initial_result is not None

        # Overwrite with different delay
        registry.set(backend, model, key, 60.0)
        new_result = registry.get(backend, model, key)
        assert new_result is not None
        assert new_result > initial_result  # Should be later timestamp


class TestParseRetryDelay:
    """Tests for parse_retry_delay function."""

    def test_parse_retry_delay_with_valid_retry_info(self) -> None:
        """Test parsing valid RetryInfo structure."""
        detail = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "30s",
                    }
                ]
            }
        }

        result = parse_retry_delay(detail)
        assert result == 30.0

    def test_parse_retry_delay_with_invalid_type(self) -> None:
        """Test parsing with invalid @type."""
        detail = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/other.Info",
                        "retryDelay": "30s",
                    }
                ]
            }
        }

        result = parse_retry_delay(detail)
        assert result is None

    def test_parse_retry_delay_with_invalid_delay_format(self) -> None:
        """Test parsing with invalid delay format."""
        detail = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "30",  # Missing 's'
                    }
                ]
            }
        }

        result = parse_retry_delay(detail)
        assert result is None

    def test_parse_retry_delay_with_non_numeric_delay(self) -> None:
        """Test parsing with non-numeric delay."""
        detail = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "invalid",
                    }
                ]
            }
        }

        result = parse_retry_delay(detail)
        assert result is None

    def test_parse_retry_delay_with_missing_details(self) -> None:
        """Test parsing with missing details."""
        detail = {"error": {}}

        result = parse_retry_delay(detail)
        assert result is None

    def test_parse_retry_delay_with_empty_details(self) -> None:
        """Test parsing with empty details list."""
        detail = {"error": {"details": []}}

        result = parse_retry_delay(detail)
        assert result is None

    def test_parse_retry_delay_with_non_dict_detail(self) -> None:
        """Test parsing with non-dict detail."""
        detail = "string detail"

        result = parse_retry_delay(detail)
        assert result is None

    def test_parse_retry_delay_with_missing_error(self) -> None:
        """Test parsing with missing error key."""
        detail = {"other": "data"}

        result = parse_retry_delay(detail)
        assert result is None

    def test_parse_retry_delay_with_multiple_details(self) -> None:
        """Test parsing with multiple details, should find first valid one."""
        detail = {
            "error": {
                "details": [
                    {"@type": "other.Info"},
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "45s",
                    },
                    {"@type": "another.Info"},
                ]
            }
        }

        result = parse_retry_delay(detail)
        assert result == 45.0

    def test_parse_retry_delay_with_json_string(self) -> None:
        """Test parsing JSON string detail."""
        json_detail = '{"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "20s"}]}}'

        result = parse_retry_delay(json_detail)
        assert result == 20.0

    def test_parse_retry_delay_with_duration_object(self) -> None:
        """Test parsing RetryInfo duration dictionaries."""
        detail = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": {"seconds": "12", "nanos": 500_000_000},
                    }
                ]
            }
        }

        result = parse_retry_delay(detail)
        assert result == pytest.approx(12.5)

    def test_parse_retry_delay_with_embedded_json(self) -> None:
        """Test parsing string with embedded JSON."""
        detail = 'prefix {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "25s"}]}} suffix'

        result = parse_retry_delay(detail)
        assert result == 25.0


class TestFindRetryDelayInDetails:
    """Tests for _find_retry_delay_in_details function."""

    def test_find_retry_delay_valid_details(self) -> None:
        """Test finding retry delay in valid details."""
        details = [
            {
                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                "retryDelay": "40s",
            }
        ]

        result = _find_retry_delay_in_details(details)
        assert result == 40.0

    def test_find_retry_delay_no_valid_details(self) -> None:
        """Test with no valid retry details."""
        details = [
            {"@type": "other.Info"},
            {"invalid": "data"},
        ]

        result = _find_retry_delay_in_details(details)
        assert result is None

    def test_find_retry_delay_empty_list(self) -> None:
        """Test with empty details list."""
        result = _find_retry_delay_in_details([])
        assert result is None

    def test_find_retry_delay_mixed_valid_invalid(self) -> None:
        """Test with mix of valid and invalid details."""
        details = [
            {"@type": "other.Info"},
            {
                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                "retryDelay": "35s",
            },
            {"another": "detail"},
        ]

        result = _find_retry_delay_in_details(details)
        assert result == 35.0


class TestAsDict:
    """Tests for _as_dict function."""

    def test_as_dict_with_dict(self) -> None:
        """Test _as_dict with dictionary input."""
        input_dict = {"key": "value"}
        result = _as_dict(input_dict)
        assert result == input_dict

    def test_as_dict_with_json_string(self) -> None:
        """Test _as_dict with JSON string."""
        json_str = '{"key": "value", "number": 42}'
        result = _as_dict(json_str)
        assert result == {"key": "value", "number": 42}

    def test_as_dict_with_invalid_json(self) -> None:
        """Test _as_dict with invalid JSON."""
        invalid_json = '{"key": "value"'  # Missing closing brace
        result = _as_dict(invalid_json)
        assert result is None

    def test_as_dict_with_embedded_json(self) -> None:
        """Test _as_dict with embedded JSON in string."""
        embedded = 'prefix {"key": "value"} suffix'
        result = _as_dict(embedded)
        assert result == {"key": "value"}

    def test_as_dict_with_no_json_in_string(self) -> None:
        """Test _as_dict with string containing no JSON."""
        no_json = "just plain text"
        result = _as_dict(no_json)
        assert result is None

    def test_as_dict_with_non_string_non_dict(self) -> None:
        """Test _as_dict with non-string, non-dict input."""
        result = _as_dict(42)
        assert result is None

        result = _as_dict(["list", "item"])
        assert result is None
