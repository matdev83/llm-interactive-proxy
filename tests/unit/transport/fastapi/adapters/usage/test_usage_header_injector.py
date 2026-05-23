"""Tests for UsageHeaderInjector."""

from __future__ import annotations

from src.core.transport.fastapi.adapters.usage.header_injector import (
    UsageHeaderInjector,
)


class TestUsageHeaderInjector:
    """Test UsageHeaderInjector implementation."""

    def test_basic_token_headers_injected(self):
        """Test that basic token headers are injected."""
        injector = UsageHeaderInjector()
        headers = {}
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }
        result = injector.inject_headers(headers, usage)
        assert result["x-usage-prompt-tokens"] == "10"
        assert result["x-usage-completion-tokens"] == "20"
        assert result["x-usage-total-tokens"] == "30"

    def test_extended_headers_when_present(self):
        """Test that extended headers are injected when present."""
        injector = UsageHeaderInjector()
        headers = {}
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "completion_tokens_details": {"reasoning_tokens": 5},
            "prompt_tokens_details": {"cached_tokens": 3},
            "cost": 0.001,
        }
        result = injector.inject_headers(headers, usage)
        assert result["x-usage-reasoning-tokens"] == "5"
        assert result["x-usage-cached-tokens"] == "3"
        assert result["x-usage-cost"] == "0.001"

    def test_missing_fields_dont_create_headers(self):
        """Test that missing fields don't create headers."""
        injector = UsageHeaderInjector()
        headers = {}
        usage = {"prompt_tokens": 10}
        result = injector.inject_headers(headers, usage)
        assert "x-usage-prompt-tokens" in result
        assert "x-usage-completion-tokens" in result  # Should be 0
        assert "x-usage-total-tokens" in result  # Should be 10
        assert "x-usage-reasoning-tokens" not in result
        assert "x-usage-cached-tokens" not in result
        assert "x-usage-cost" not in result

    def test_existing_headers_preserved(self):
        """Test that existing headers are preserved."""
        injector = UsageHeaderInjector()
        headers = {"x-custom": "value", "authorization": "Bearer token"}
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        result = injector.inject_headers(headers, usage)
        assert result["x-custom"] == "value"
        assert result["authorization"] == "Bearer token"
        assert result["x-usage-prompt-tokens"] == "10"

    def test_none_usage_handling(self):
        """Test that None usage doesn't add headers."""
        injector = UsageHeaderInjector()
        headers = {"x-custom": "value"}
        result = injector.inject_headers(headers, None)
        assert result == {"x-custom": "value"}

    def test_empty_usage_handling(self):
        """Test that empty usage adds zero headers."""
        injector = UsageHeaderInjector()
        headers = {}
        result = injector.inject_headers(headers, {})
        assert result["x-usage-prompt-tokens"] == "0"
        assert result["x-usage-completion-tokens"] == "0"
        assert result["x-usage-total-tokens"] == "0"

    def test_float_cost_conversion(self):
        """Test that float cost is converted to string."""
        injector = UsageHeaderInjector()
        headers = {}
        usage = {"cost": 0.001234}
        result = injector.inject_headers(headers, usage)
        assert result["x-usage-cost"] == "0.001234"

    def test_none_cost_not_added(self):
        """Test that None cost is not added."""
        injector = UsageHeaderInjector()
        headers = {}
        usage = {"prompt_tokens": 10, "cost": None}
        result = injector.inject_headers(headers, usage)
        assert "x-usage-cost" not in result

    def test_audio_tokens_header(self):
        """Test that audio_tokens header is added when present."""
        injector = UsageHeaderInjector()
        headers = {}
        usage = {
            "prompt_tokens": 10,
            "prompt_tokens_details": {"audio_tokens": 5},
        }
        result = injector.inject_headers(headers, usage)
        assert result["x-usage-audio-tokens"] == "5"
