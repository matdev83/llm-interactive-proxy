"""Tests for OpenRouter backend initialization strategy."""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.openrouter import OpenRouterInitializationStrategy
from src.connectors.strategies.registry import initialization_strategy_registry
from src.core.config.models.backends import get_openrouter_headers


class TestOpenRouterInitializationStrategy:
    """Tests for the OpenRouter initialization strategy."""

    def test_strategy_sets_key_name_to_openrouter(self) -> None:
        """Test that strategy sets key_name to 'openrouter'."""
        strategy = OpenRouterInitializationStrategy()
        config = {"api_key": "test-key", "api_base_url": "https://api.openrouter.ai"}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "openrouter"

    def test_strategy_preserves_other_config_values(self) -> None:
        """Test that strategy preserves all other configuration values."""
        strategy = OpenRouterInitializationStrategy()
        config = {
            "api_key": "test-key",
            "api_base_url": "https://custom.openrouter.ai",
            "auth_header_name": "x-api-key",
            "extra_field": "extra-value",
        }

        result = strategy.augment_init_config(config)

        assert result["api_key"] == "test-key"
        assert result["api_base_url"] == "https://custom.openrouter.ai"
        assert result["auth_header_name"] == "x-api-key"
        assert result["extra_field"] == "extra-value"
        assert result["key_name"] == "openrouter"

    def test_strategy_sets_openrouter_headers_provider(self) -> None:
        """Test that strategy sets openrouter_headers_provider correctly."""
        strategy = OpenRouterInitializationStrategy()
        config = {"api_key": "test-key"}

        result = strategy.augment_init_config(config)

        assert "openrouter_headers_provider" in result
        assert result["openrouter_headers_provider"] is get_openrouter_headers

    def test_strategy_sets_default_api_base_url_when_not_present(self) -> None:
        """Test that strategy sets default api_base_url when not present."""
        strategy = OpenRouterInitializationStrategy()
        config = {"api_key": "test-key"}

        result = strategy.augment_init_config(config)

        assert "api_base_url" in result
        assert result["api_base_url"] == "https://openrouter.ai/api/v1"

    def test_strategy_preserves_existing_api_base_url(self) -> None:
        """Test that strategy preserves existing api_base_url when present."""
        strategy = OpenRouterInitializationStrategy()
        config = {
            "api_key": "test-key",
            "api_base_url": "https://custom.openrouter.ai/api/v1",
        }

        result = strategy.augment_init_config(config)

        assert result["api_base_url"] == "https://custom.openrouter.ai/api/v1"

    def test_strategy_returns_new_dict_does_not_mutate_input(self) -> None:
        """Test that strategy returns a new dict and does not mutate input."""
        strategy = OpenRouterInitializationStrategy()
        config = {"api_key": "test-key"}

        result = strategy.augment_init_config(config)

        assert result is not config
        assert "key_name" not in config
        assert "openrouter_headers_provider" not in config
        assert "api_base_url" not in config
        assert result["key_name"] == "openrouter"
        assert result["openrouter_headers_provider"] is get_openrouter_headers
        assert result["api_base_url"] == "https://openrouter.ai/api/v1"

    def test_strategy_overwrites_existing_key_name(self) -> None:
        """Test that strategy overwrites existing key_name value."""
        strategy = OpenRouterInitializationStrategy()
        config = {"api_key": "test-key", "key_name": "other-value"}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "openrouter"
        assert result["key_name"] != "other-value"

    def test_strategy_handles_empty_config(self) -> None:
        """Test that strategy handles empty configuration."""
        strategy = OpenRouterInitializationStrategy()
        config: dict[str, Any] = {}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "openrouter"
        assert result["openrouter_headers_provider"] is get_openrouter_headers
        assert result["api_base_url"] == "https://openrouter.ai/api/v1"

    def test_strategy_handles_nested_config_values(self) -> None:
        """Test that strategy handles nested configuration structures."""
        strategy = OpenRouterInitializationStrategy()
        config = {
            "api_key": "test-key",
            "extra": {"nested": "value", "list": [1, 2, 3]},
        }

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "openrouter"
        assert result["api_key"] == "test-key"
        assert result["extra"] == config["extra"]
        assert result["extra"]["nested"] == "value"
        assert result["extra"]["list"] == [1, 2, 3]

    def test_strategy_is_registered_with_registry(self) -> None:
        """Test that OpenRouter strategy is registered with the global registry."""
        strategy = initialization_strategy_registry.get_strategy("openrouter")

        assert strategy is not None
        assert isinstance(strategy, OpenRouterInitializationStrategy) or hasattr(
            strategy, "augment_init_config"
        )

        # Verify it works correctly
        config = {"api_key": "test-key"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "openrouter"
        assert result["openrouter_headers_provider"] is get_openrouter_headers
        assert result["api_base_url"] == "https://openrouter.ai/api/v1"

    def test_strategy_registry_returns_openrouter_strategy(self) -> None:
        """Test that registry returns OpenRouter strategy for 'openrouter' connector type."""
        # Get strategy from registry
        strategy = initialization_strategy_registry.get_strategy("openrouter")

        # Verify it's the correct strategy by checking behavior
        config = {"api_key": "test-key", "some_other_field": "value"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "openrouter"
        assert result["api_key"] == "test-key"
        assert result["some_other_field"] == "value"
        assert result["openrouter_headers_provider"] is get_openrouter_headers
        assert result["api_base_url"] == "https://openrouter.ai/api/v1"
