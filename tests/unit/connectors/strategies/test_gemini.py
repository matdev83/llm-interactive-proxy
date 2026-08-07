"""Tests for Gemini backend initialization strategy."""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.gemini import GeminiInitializationStrategy
from src.connectors.strategies.registry import initialization_strategy_registry


class TestGeminiInitializationStrategy:
    """Tests for the Gemini initialization strategy."""

    def test_strategy_sets_key_name_to_x_goog_api_key(self) -> None:
        """Test that strategy sets key_name to 'x-goog-api-key'."""
        strategy = GeminiInitializationStrategy()
        config = {"api_key": "test-key", "api_base_url": "https://api.gemini.com"}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "x-goog-api-key"

    def test_strategy_preserves_other_config_values(self) -> None:
        """Test that strategy preserves all other configuration values."""
        strategy = GeminiInitializationStrategy()
        config = {
            "api_key": "test-key",
            "api_base_url": "https://api.gemini.com",
            "gemini_api_base_url": "https://custom.gemini.com",
            "auth_header_name": "x-api-key",
        }

        result = strategy.augment_init_config(config)

        assert result["api_key"] == "test-key"
        assert result["auth_header_name"] == "x-api-key"
        assert result["key_name"] == "x-goog-api-key"

    def test_strategy_maps_api_base_url_to_gemini_api_base_url(self) -> None:
        """Test that strategy maps api_base_url to gemini_api_base_url when present."""
        strategy = GeminiInitializationStrategy()
        config = {"api_key": "test-key", "api_base_url": "https://custom.gemini.com"}

        result = strategy.augment_init_config(config)

        assert "gemini_api_base_url" in result
        assert result["gemini_api_base_url"] == "https://custom.gemini.com"
        # Original BackendFactory behavior preserves api_base_url after mapping
        assert "api_base_url" in result
        assert result["api_base_url"] == "https://custom.gemini.com"

    def test_strategy_sets_default_gemini_api_base_url_when_not_present(self) -> None:
        """Test that strategy sets default gemini_api_base_url when neither api_base_url nor gemini_api_base_url present."""
        strategy = GeminiInitializationStrategy()
        config = {"api_key": "test-key"}

        result = strategy.augment_init_config(config)

        assert "gemini_api_base_url" in result
        assert (
            result["gemini_api_base_url"] == "https://generativelanguage.googleapis.com"
        )

    def test_strategy_preserves_existing_gemini_api_base_url(self) -> None:
        """Test that strategy preserves existing gemini_api_base_url when present."""
        strategy = GeminiInitializationStrategy()
        config = {
            "api_key": "test-key",
            "gemini_api_base_url": "https://custom.gemini.com",
        }

        result = strategy.augment_init_config(config)

        assert result["gemini_api_base_url"] == "https://custom.gemini.com"

    def test_strategy_returns_new_dict_does_not_mutate_input(self) -> None:
        """Test that strategy returns a new dict and does not mutate input."""
        strategy = GeminiInitializationStrategy()
        config = {"api_key": "test-key", "api_base_url": "https://api.gemini.com"}

        result = strategy.augment_init_config(config)

        assert result is not config
        assert "key_name" not in config
        assert "gemini_api_base_url" not in config
        assert result["key_name"] == "x-goog-api-key"
        assert result["gemini_api_base_url"] == "https://api.gemini.com"
        # Original BackendFactory behavior preserves api_base_url
        assert result["api_base_url"] == "https://api.gemini.com"

    def test_strategy_overwrites_existing_key_name(self) -> None:
        """Test that strategy overwrites existing key_name value."""
        strategy = GeminiInitializationStrategy()
        config = {"api_key": "test-key", "key_name": "other-value"}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "x-goog-api-key"
        assert result["key_name"] != "other-value"

    def test_strategy_handles_empty_config(self) -> None:
        """Test that strategy handles empty configuration."""
        strategy = GeminiInitializationStrategy()
        config: dict[str, Any] = {}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "x-goog-api-key"
        assert (
            result["gemini_api_base_url"] == "https://generativelanguage.googleapis.com"
        )

    def test_strategy_handles_nested_config_values(self) -> None:
        """Test that strategy handles nested configuration structures."""
        strategy = GeminiInitializationStrategy()
        config = {
            "api_key": "test-key",
            "extra": {"nested": "value", "list": [1, 2, 3]},
        }

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "x-goog-api-key"
        assert result["api_key"] == "test-key"
        assert result["extra"] == config["extra"]
        assert result["extra"]["nested"] == "value"
        assert result["extra"]["list"] == [1, 2, 3]

    def test_strategy_is_registered_with_registry(self) -> None:
        """Test that Gemini strategy is registered with the global registry."""
        strategy = initialization_strategy_registry.get_strategy("gemini")

        assert strategy is not None
        assert isinstance(strategy, GeminiInitializationStrategy) or hasattr(
            strategy, "augment_init_config"
        )

        # Verify it works correctly
        config = {"api_key": "test-key"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "x-goog-api-key"

    def test_strategy_registry_returns_gemini_strategy(self) -> None:
        """Test that registry returns Gemini strategy for 'gemini' connector type."""
        # Get strategy from registry
        strategy = initialization_strategy_registry.get_strategy("gemini")

        # Verify it's the correct strategy by checking behavior
        config = {"api_key": "test-key", "some_other_field": "value"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "x-goog-api-key"
        assert result["api_key"] == "test-key"
        assert result["some_other_field"] == "value"
