"""Tests for example backend initialization strategy.

This test module demonstrates OCP-compliant extension by proving that:
1. A new strategy can be registered without editing BackendFactory or BackendStage
2. The registry correctly selects the example strategy
3. The strategy's augmentation behavior works as expected
4. Default strategy behavior is preserved for unknown connector types
"""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.example_backend import (
    ExampleBackendInitializationStrategy,
)
from src.connectors.strategies.registry import (
    initialization_strategy_registry,
)


class TestExampleBackendInitializationStrategy:
    """Tests for the example backend initialization strategy.

    These tests prove that adding a new strategy requires no changes to
    BackendFactory or BackendStage, demonstrating OCP compliance.
    """

    def test_strategy_sets_key_name_to_example_backend(self) -> None:
        """Test that strategy sets key_name to 'example_backend'."""
        strategy = ExampleBackendInitializationStrategy()
        config = {"api_key": "test-key", "api_base_url": "https://api.example.com"}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "example_backend"

    def test_strategy_adds_example_config_field(self) -> None:
        """Test that strategy adds example_config field."""
        strategy = ExampleBackendInitializationStrategy()
        config = {"api_key": "test-key"}

        result = strategy.augment_init_config(config)

        assert result["example_config"] == "example_value"

    def test_strategy_preserves_other_config_values(self) -> None:
        """Test that strategy preserves all other configuration values."""
        strategy = ExampleBackendInitializationStrategy()
        config = {
            "api_key": "test-key",
            "api_base_url": "https://api.example.com",
            "custom_field": "custom-value",
        }

        result = strategy.augment_init_config(config)

        assert result["api_key"] == "test-key"
        assert result["api_base_url"] == "https://api.example.com"
        assert result["custom_field"] == "custom-value"
        assert result["key_name"] == "example_backend"
        assert result["example_config"] == "example_value"

    def test_strategy_returns_new_dict_does_not_mutate_input(self) -> None:
        """Test that strategy returns a new dict and does not mutate input."""
        strategy = ExampleBackendInitializationStrategy()
        config = {"api_key": "test-key"}

        result = strategy.augment_init_config(config)

        assert result is not config
        assert "key_name" not in config
        assert "example_config" not in config
        assert result["key_name"] == "example_backend"
        assert result["example_config"] == "example_value"

    def test_strategy_overwrites_existing_key_name(self) -> None:
        """Test that strategy overwrites existing key_name value."""
        strategy = ExampleBackendInitializationStrategy()
        config = {"api_key": "test-key", "key_name": "other-value"}

        result = strategy.augment_init_config(config)

        assert result["key_name"] == "example_backend"
        assert result["key_name"] != "other-value"

    def test_strategy_handles_empty_config(self) -> None:
        """Test that strategy handles empty configuration."""
        strategy = ExampleBackendInitializationStrategy()
        config: dict[str, Any] = {}

        result = strategy.augment_init_config(config)

        assert result == {
            "key_name": "example_backend",
            "example_config": "example_value",
        }

    def test_strategy_is_registered_with_registry(self) -> None:
        """Test that example strategy is registered with the global registry.

        This proves that the strategy can be discovered without modifying
        BackendFactory or BackendStage - demonstrating OCP compliance.
        """
        # Import the example_backend module to trigger registration
        import src.connectors.strategies.example_backend  # type: ignore[reportUnusedImport] # noqa: F401

        strategy = initialization_strategy_registry.get_strategy("example_backend")

        assert strategy is not None
        # Verify it works correctly
        config = {"api_key": "test-key"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "example_backend"
        assert result["example_config"] == "example_value"

    def test_strategy_registry_returns_example_strategy(self) -> None:
        """Test that registry returns example strategy for 'example_backend' connector type.

        This test proves that the registry correctly selects the example strategy,
        demonstrating that new strategies are automatically discovered.
        """
        # Import the example_backend module to trigger registration
        import src.connectors.strategies.example_backend  # type: ignore[reportUnusedImport] # noqa: F401

        # Get strategy from registry
        strategy = initialization_strategy_registry.get_strategy("example_backend")

        # Verify it's the correct strategy by checking behavior
        config = {"api_key": "test-key", "some_other_field": "value"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "example_backend"
        assert result["example_config"] == "example_value"
        assert result["api_key"] == "test-key"
        assert result["some_other_field"] == "value"


class TestOCPCompliance:
    """Tests proving OCP-compliant extension without modifying existing code."""

    def test_registry_returns_default_strategy_for_unknown_connector(self) -> None:
        """Test that registry returns default strategy for unknown connector types.

        This proves that the default strategy behavior is preserved, and
        unknown connector types fall back gracefully without errors.
        """
        # Use a connector type that definitely doesn't have a registered strategy
        strategy = initialization_strategy_registry.get_strategy(
            "unknown_connector_xyz"
        )

        # Should return default strategy
        assert strategy is not None
        # Default strategy should pass config unmodified (except for copy)
        config = {"api_key": "test-key", "custom_field": "value"}
        result = strategy.augment_init_config(config)

        assert result == config
        assert result is not config  # Should return a copy

    def test_example_strategy_can_be_added_without_factory_modification(self) -> None:
        """Test that example strategy works without BackendFactory changes.

        This test demonstrates that adding a new strategy requires no changes
        to BackendFactory - the registry pattern handles strategy selection.
        """
        # Import to trigger registration
        import src.connectors.strategies.example_backend  # type: ignore[reportUnusedImport] # noqa: F401

        # Verify registry can retrieve the strategy
        strategy = initialization_strategy_registry.get_strategy("example_backend")
        assert strategy is not None

        # Verify strategy behavior
        config = {"api_key": "test-key"}
        result = strategy.augment_init_config(config)

        # Strategy should augment config correctly
        assert result["key_name"] == "example_backend"
        assert result["example_config"] == "example_value"

        # This test proves that BackendFactory doesn't need modification
        # because it uses the registry, which automatically discovers strategies

    def test_example_strategy_can_be_added_without_stage_modification(self) -> None:
        """Test that example strategy works without BackendStage changes.

        This test demonstrates that adding a new strategy requires no changes
        to BackendStage - validation uses BackendFactory, which uses the registry.
        """
        # Import to trigger registration
        import src.connectors.strategies.example_backend  # type: ignore[reportUnusedImport] # noqa: F401

        # Verify registry can retrieve the strategy
        strategy = initialization_strategy_registry.get_strategy("example_backend")
        assert strategy is not None

        # Verify strategy works
        config = {"api_key": "test-key"}
        result = strategy.augment_init_config(config)

        assert result["key_name"] == "example_backend"

        # This test proves that BackendStage doesn't need modification
        # because it delegates to BackendValidationService, which uses
        # BackendFactory, which uses the registry pattern

    def test_multiple_strategies_can_coexist(self) -> None:
        """Test that multiple strategies can coexist without conflicts.

        This proves that the registry pattern supports multiple strategies
        and that adding new ones doesn't break existing ones.
        """
        # Import example strategy
        import src.connectors.strategies.example_backend  # type: ignore[reportUnusedImport] # noqa: F401

        # Verify example strategy works
        example_strategy = initialization_strategy_registry.get_strategy(
            "example_backend"
        )
        assert example_strategy is not None
        example_result = example_strategy.augment_init_config({"api_key": "test"})
        assert example_result["key_name"] == "example_backend"

        # Verify existing strategies still work (anthropic should be registered)
        anthropic_strategy = initialization_strategy_registry.get_strategy("anthropic")
        assert anthropic_strategy is not None
        anthropic_result = anthropic_strategy.augment_init_config({"api_key": "test"})
        assert anthropic_result["key_name"] == "anthropic"

        # Verify default strategy still works for unknown types
        default_strategy = initialization_strategy_registry.get_strategy("unknown")
        assert default_strategy is not None
        default_result = default_strategy.augment_init_config({"api_key": "test"})
        assert default_result == {"api_key": "test"}
