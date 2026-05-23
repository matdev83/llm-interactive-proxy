"""Tests for Anthropic backend initialization strategy."""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.anthropic import AnthropicInitializationStrategy
from src.connectors.strategies.registry import initialization_strategy_registry


class TestAnthropicInitializationStrategy:
    """Tests for the Anthropic initialization strategy."""

    def test_strategy_sets_key_name_to_anthropic(self) -> None:
        """Test that strategy sets key_name to 'anthropic'."""
        strategy = AnthropicInitializationStrategy()
        config = {"api_key": "test-key", "api_base_url": "https://api.anthropic.com"}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "anthropic"

    def test_strategy_preserves_other_config_values(self) -> None:
        """Test that strategy preserves all other configuration values."""
        strategy = AnthropicInitializationStrategy()
        config = {
            "api_key": "test-key",
            "api_base_url": "https://api.anthropic.com",
            "anthropic_api_base_url": "https://custom.anthropic.com",
            "auth_header_name": "x-api-key",
        }

        result = strategy.augment_init_config(config)

        assert result["api_key"] == "test-key"
        assert result["api_base_url"] == "https://api.anthropic.com"
        assert result["anthropic_api_base_url"] == "https://custom.anthropic.com"
        assert result["auth_header_name"] == "x-api-key"
        assert result["key_name"] == "anthropic"

    def test_strategy_returns_new_dict_does_not_mutate_input(self) -> None:
        """Test that strategy returns a new dict and does not mutate input."""
        strategy = AnthropicInitializationStrategy()
        config = {"api_key": "test-key"}

        result = strategy.augment_init_config(config)

        assert result is not config
        assert "key_name" not in config
        assert result["key_name"] == "anthropic"

    def test_strategy_overwrites_existing_key_name(self) -> None:
        """Test that strategy overwrites existing key_name value."""
        strategy = AnthropicInitializationStrategy()
        config = {"api_key": "test-key", "key_name": "other-value"}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "anthropic"
        assert result["key_name"] != "other-value"

    def test_strategy_handles_empty_config(self) -> None:
        """Test that strategy handles empty configuration."""
        strategy = AnthropicInitializationStrategy()
        config: dict[str, Any] = {}

        result = strategy.augment_init_config(config)

        assert result == {"key_name": "anthropic"}

    def test_strategy_handles_nested_config_values(self) -> None:
        """Test that strategy handles nested configuration structures."""
        strategy = AnthropicInitializationStrategy()
        config = {
            "api_key": "test-key",
            "extra": {"nested": "value", "list": [1, 2, 3]},
        }

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "anthropic"
        assert result["api_key"] == "test-key"
        assert result["extra"] == config["extra"]
        assert result["extra"]["nested"] == "value"
        assert result["extra"]["list"] == [1, 2, 3]

    def test_strategy_is_registered_with_registry(self) -> None:
        """Test that Anthropic strategy is registered with the global registry."""
        strategy = initialization_strategy_registry.get_strategy("anthropic")

        assert strategy is not None
        assert isinstance(strategy, AnthropicInitializationStrategy) or hasattr(
            strategy, "augment_init_config"
        )

        # Verify it works correctly
        config = {"api_key": "test-key"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "anthropic"

    def test_strategy_registry_returns_anthropic_strategy(self) -> None:
        """Test that registry returns Anthropic strategy for 'anthropic' connector type."""
        # Get strategy from registry
        strategy = initialization_strategy_registry.get_strategy("anthropic")

        # Verify it's the correct strategy by checking behavior
        config = {"api_key": "test-key", "some_other_field": "value"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "anthropic"
        assert result["api_key"] == "test-key"
        assert result["some_other_field"] == "value"
