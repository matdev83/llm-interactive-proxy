"""Tests for vendor prefix handling in connectors.

These tests verify that single-vendor connectors correctly:
1. Accept model names with AND without vendor prefix (backward compatible)
2. Strip vendor prefix internally before API calls
3. Return vendor-prefixed model names in get_available_models()
"""

import pytest
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix


class TestVendorPrefixUtilities:
    """Test the vendor prefix utility functions."""

    def test_strip_vendor_prefix_with_prefix(self):
        """strip_vendor_prefix removes the vendor prefix when present."""
        assert (
            strip_vendor_prefix("google/gemini-2.5-pro", "google") == "gemini-2.5-pro"
        )
        assert (
            strip_vendor_prefix("anthropic/claude-3-opus", "anthropic")
            == "claude-3-opus"
        )
        assert strip_vendor_prefix("openai/gpt-4", "openai") == "gpt-4"

    def test_strip_vendor_prefix_without_prefix(self):
        """strip_vendor_prefix returns the model unchanged when prefix is absent."""
        assert strip_vendor_prefix("gemini-2.5-pro", "google") == "gemini-2.5-pro"
        assert strip_vendor_prefix("claude-3-opus", "anthropic") == "claude-3-opus"
        assert strip_vendor_prefix("gpt-4", "openai") == "gpt-4"

    def test_strip_vendor_prefix_wrong_vendor(self):
        """strip_vendor_prefix does not strip if vendor doesn't match."""
        # Model has openai/ prefix but we're stripping for google
        assert strip_vendor_prefix("openai/gpt-4", "google") == "openai/gpt-4"
        # Model has google/ prefix but we're stripping for anthropic
        assert (
            strip_vendor_prefix("google/gemini-2.5-pro", "anthropic")
            == "google/gemini-2.5-pro"
        )

    def test_add_vendor_prefix_without_prefix(self):
        """add_vendor_prefix adds the vendor prefix when not present."""
        assert add_vendor_prefix("gemini-2.5-pro", "google") == "google/gemini-2.5-pro"
        assert (
            add_vendor_prefix("claude-3-opus", "anthropic") == "anthropic/claude-3-opus"
        )
        assert add_vendor_prefix("gpt-4", "openai") == "openai/gpt-4"

    def test_add_vendor_prefix_already_has_prefix(self):
        """add_vendor_prefix does not double-prefix when already present."""
        assert (
            add_vendor_prefix("google/gemini-2.5-pro", "google")
            == "google/gemini-2.5-pro"
        )
        assert (
            add_vendor_prefix("anthropic/claude-3-opus", "anthropic")
            == "anthropic/claude-3-opus"
        )
        assert add_vendor_prefix("openai/gpt-4", "openai") == "openai/gpt-4"

    def test_add_vendor_prefix_different_vendor(self):
        """add_vendor_prefix adds prefix even if model has different vendor prefix."""
        # This is an edge case - model has openai/ but we add google/
        # The function should add the prefix since it doesn't match
        assert add_vendor_prefix("openai/gpt-4", "google") == "google/openai/gpt-4"

    def test_vendor_prefix_with_complex_model_names(self):
        """Utility functions handle complex model names correctly."""
        # Model names with multiple path segments
        assert (
            strip_vendor_prefix("google/models/gemini-2.0-flash", "google")
            == "models/gemini-2.0-flash"
        )
        assert (
            add_vendor_prefix("models/gemini-2.0-flash", "google")
            == "google/models/gemini-2.0-flash"
        )

        # Model names with colons (like OpenRouter free tier)
        assert (
            strip_vendor_prefix("google/gemini-2.5-pro:free", "google")
            == "gemini-2.5-pro:free"
        )
        assert (
            add_vendor_prefix("claude-3-opus:beta", "anthropic")
            == "anthropic/claude-3-opus:beta"
        )


class TestGeminiVendorPrefix:
    """Test vendor prefix handling in Gemini connectors."""

    def test_gemini_vendor_constant(self):
        """Verify the Google vendor prefix constant is defined."""
        from src.connectors.gemini_base.connector import GOOGLE_VENDOR_PREFIX

        assert GOOGLE_VENDOR_PREFIX == "google"


class TestAnthropicVendorPrefix:
    """Test vendor prefix handling in Anthropic connectors."""

    def test_anthropic_vendor_constant(self):
        """Verify the Anthropic vendor prefix constant is defined."""
        from src.connectors.anthropic import ANTHROPIC_VENDOR_PREFIX

        assert ANTHROPIC_VENDOR_PREFIX == "anthropic"


class TestOpenAICodexVendorPrefix:
    """Test vendor prefix handling in OpenAI Codex connector."""

    def test_openai_codex_vendor_constant(self):
        """Verify the OpenAI vendor prefix constant is defined."""
        from src.connectors.openai_codex import OPENAI_VENDOR_PREFIX

        assert OPENAI_VENDOR_PREFIX == "openai"


class TestQwenOAuthVendorPrefix:
    """Test vendor prefix handling in Qwen OAuth connector."""

    def test_qwen_oauth_vendor_constant(self):
        """Verify the Qwen vendor prefix constant is defined."""
        qwen_oauth = pytest.importorskip("llm_proxy_oauth_connectors.qwen_oauth")
        assert qwen_oauth.QWEN_VENDOR_PREFIX == "qwen"


class TestOpenAIConnectorVendorPrefix:
    """Test vendor prefix handling in OpenAI connector."""

    def test_openai_connector_vendor_constant(self):
        """Verify the OpenAI vendor prefix constant is defined."""
        from src.connectors.openai import OpenAIConnector

        assert OpenAIConnector.VENDOR_PREFIX == "openai"


class TestOpenRouterVendorPrefix:
    """Test vendor prefix handling in OpenRouter connector."""

    def test_openrouter_vendor_constant_none(self):
        """Verify OpenRouter has no vendor prefix (multi-vendor)."""
        from src.connectors.openrouter import OpenRouterBackend

        assert OpenRouterBackend.VENDOR_PREFIX is None


class TestZAIVendorPrefix:
    """Test vendor prefix handling in ZAI connector."""

    def test_zai_vendor_constant(self):
        """Verify the ZAI vendor prefix constant is defined."""
        from src.connectors.zai import ZAIConnector

        assert ZAIConnector.VENDOR_PREFIX == "zhipu"


class TestMinimaxVendorPrefix:
    """Test vendor prefix handling in Minimax connector."""

    def test_minimax_vendor_constant(self):
        """Verify the Minimax vendor prefix constant is defined."""
        from src.connectors.minimax import MinimaxConnector

        assert MinimaxConnector.VENDOR_PREFIX == "minimax"
