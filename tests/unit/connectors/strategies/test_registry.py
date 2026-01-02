"""Tests for backend initialization strategy registry."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from src.core.common.exceptions import ConfigurationError, LLMProxyError
from src.core.interfaces.backend_initialization_strategy_interface import (
    IBackendInitializationStrategy,
)


class TestDefaultInitializationStrategy:
    """Tests for the default initialization strategy."""

    def test_default_strategy_returns_config_unmodified(self) -> None:
        """Test that default strategy returns config unmodified."""
        from src.connectors.strategies.registry import DefaultInitializationStrategy

        strategy = DefaultInitializationStrategy()
        config = {"api_key": "test-key", "api_base_url": "https://api.example.com"}

        result = strategy.augment_init_config(config)

        assert result == config
        assert result is not config  # Should return a copy or new dict

    def test_default_strategy_handles_empty_config(self) -> None:
        """Test that default strategy handles empty config."""
        from src.connectors.strategies.registry import DefaultInitializationStrategy

        strategy = DefaultInitializationStrategy()
        config: dict[str, Any] = {}

        result = strategy.augment_init_config(config)

        assert result == {}
        assert result is not config

    def test_default_strategy_handles_nested_config(self) -> None:
        """Test that default strategy handles nested config structures."""
        from src.connectors.strategies.registry import DefaultInitializationStrategy

        strategy = DefaultInitializationStrategy()
        config = {
            "api_key": "test-key",
            "extra": {"nested": "value", "list": [1, 2, 3]},
        }

        result = strategy.augment_init_config(config)

        assert result == config
        assert result["extra"] == config["extra"]


class TestInitializationStrategyRegistry:
    """Tests for the initialization strategy registry."""

    def test_registry_returns_default_strategy_when_none_registered(self) -> None:
        """Test that registry returns default strategy when no custom strategy registered."""
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()
        config = {"api_key": "test-key"}

        strategy = registry.get_strategy("unknown_connector")
        result = strategy.augment_init_config(config)

        assert result == config

    def test_registry_registers_and_retrieves_custom_strategy(self) -> None:
        """Test that registry can register and retrieve a custom strategy."""
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()

        # Create a mock strategy
        mock_strategy = MagicMock(spec=IBackendInitializationStrategy)
        mock_strategy.augment_init_config.return_value = {
            "api_key": "test-key",
            "custom_field": "custom-value",
        }

        # Register the strategy
        registry.register_strategy("test_connector", mock_strategy)

        # Retrieve and use the strategy
        strategy = registry.get_strategy("test_connector")
        result = strategy.augment_init_config({"api_key": "test-key"})

        assert result["custom_field"] == "custom-value"
        mock_strategy.augment_init_config.assert_called_once_with(
            {"api_key": "test-key"}
        )

    def test_registry_logs_warning_when_custom_strategy_not_found(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that registry logs warning when custom strategy not found."""
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()

        with caplog.at_level("WARNING"):
            strategy = registry.get_strategy("unknown_connector")
            strategy.augment_init_config({"api_key": "test"})

        # Verify warning was logged
        warning_logs = [
            record
            for record in caplog.records
            if record.levelname == "WARNING"
            and "unknown_connector" in record.message.lower()
        ]
        assert len(warning_logs) > 0
        assert "default strategy" in warning_logs[0].message.lower()

    def test_registry_exception_propagation_includes_connector_context(self) -> None:
        """Test that exceptions from strategies include connector context."""
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()

        # Create a strategy that raises an exception
        failing_strategy = MagicMock(spec=IBackendInitializationStrategy)
        original_error = ValueError("Original error message")
        failing_strategy.augment_init_config.side_effect = original_error

        registry.register_strategy("failing_connector", failing_strategy)

        # Get strategy and call it
        strategy = registry.get_strategy("failing_connector")

        # Exception should be raised with connector context
        with pytest.raises(ValueError) as exc_info:
            strategy.augment_init_config({"api_key": "test"})

        # Verify exception message includes connector context
        assert "failing_connector" in str(exc_info.value).lower()
        assert "original error" in str(exc_info.value).lower()

    def test_registry_preserves_llmproxy_error_subclasses(self) -> None:
        """Test that LLMProxyError subclasses are preserved with connector context."""
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()

        # Create a strategy that raises a ConfigurationError (LLMProxyError subclass)
        failing_strategy = MagicMock(spec=IBackendInitializationStrategy)
        original_error = ConfigurationError(
            "Invalid configuration",
            details={"field": "api_key", "reason": "missing"},
        )
        failing_strategy.augment_init_config.side_effect = original_error

        registry.register_strategy("config_error_connector", failing_strategy)

        # Get strategy and call it
        strategy = registry.get_strategy("config_error_connector")

        # Exception should be raised as ConfigurationError (preserved type)
        with pytest.raises(ConfigurationError) as exc_info:
            strategy.augment_init_config({"api_key": "test"})

        # Verify exception is still ConfigurationError
        assert isinstance(exc_info.value, ConfigurationError)
        assert isinstance(exc_info.value, LLMProxyError)

        # Verify exception message includes connector context
        assert "config_error_connector" in str(exc_info.value).lower()
        assert "invalid configuration" in str(exc_info.value).lower()

        # Verify details are preserved and connector_type is added
        assert exc_info.value.details is not None
        assert exc_info.value.details.get("connector_type") == "config_error_connector"
        assert exc_info.value.details.get("field") == "api_key"
        assert exc_info.value.details.get("reason") == "missing"

        # Verify status_code is preserved
        assert exc_info.value.status_code == 400

    def test_registry_multiple_strategies_can_be_registered(self) -> None:
        """Test that multiple strategies can be registered for different connectors."""
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()

        # Register multiple strategies
        strategy1 = MagicMock(spec=IBackendInitializationStrategy)
        strategy1.augment_init_config.return_value = {"connector": "connector1"}

        strategy2 = MagicMock(spec=IBackendInitializationStrategy)
        strategy2.augment_init_config.return_value = {"connector": "connector2"}

        registry.register_strategy("connector1", strategy1)
        registry.register_strategy("connector2", strategy2)

        # Verify both strategies can be retrieved
        retrieved1 = registry.get_strategy("connector1")
        retrieved2 = registry.get_strategy("connector2")

        assert retrieved1.augment_init_config({})["connector"] == "connector1"
        assert retrieved2.augment_init_config({})["connector"] == "connector2"

    def test_registry_strategy_replacement_overwrites_existing(self) -> None:
        """Test that registering a strategy with existing connector type overwrites it."""
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()

        # Register initial strategy
        initial_strategy = MagicMock(spec=IBackendInitializationStrategy)
        initial_strategy.augment_init_config.return_value = {"version": "1.0"}

        registry.register_strategy("test_connector", initial_strategy)

        # Register replacement strategy
        replacement_strategy = MagicMock(spec=IBackendInitializationStrategy)
        replacement_strategy.augment_init_config.return_value = {"version": "2.0"}

        registry.register_strategy("test_connector", replacement_strategy)

        # Verify replacement strategy is used
        strategy = registry.get_strategy("test_connector")
        result = strategy.augment_init_config({})

        assert result["version"] == "2.0"
        replacement_strategy.augment_init_config.assert_called_once()

    def test_registry_get_strategy_with_empty_string(self) -> None:
        """Test that registry handles empty string connector type."""
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()

        # Should return default strategy and log warning
        with patch.object(registry, "_logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            strategy = registry.get_strategy("")

            assert strategy is not None
            result = strategy.augment_init_config({"test": "value"})
            assert result == {"test": "value"}

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            assert "default strategy" in mock_logger.warning.call_args[0][0].lower()

    def test_registry_thread_safety(self) -> None:
        """Test that registry operations are thread-safe."""
        import threading

        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        registry = InitializationStrategyRegistry()
        results: list[str] = []
        errors: list[Exception] = []

        def register_and_get(connector_type: str) -> None:
            try:
                strategy = MagicMock(spec=IBackendInitializationStrategy)
                strategy.augment_init_config.return_value = {
                    "connector": connector_type,
                }
                registry.register_strategy(connector_type, strategy)
                retrieved = registry.get_strategy(connector_type)
                result = retrieved.augment_init_config({})
                results.append(result["connector"])
            except Exception as e:
                errors.append(e)

        # Create multiple threads
        threads = [
            threading.Thread(target=register_and_get, args=(f"connector_{i}",))
            for i in range(10)
        ]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        assert len(errors) == 0
        assert len(results) == 10
        assert len(set(results)) == 10  # All unique connector types


class TestStrategyAutoDiscovery:
    """Tests for automatic strategy discovery (Fix 4)."""

    def test_importing_registry_auto_discovers_strategies(self) -> None:
        """Test that importing registry.py automatically discovers and registers strategies."""
        # The registry auto-discovers strategies when imported.
        # Verify that known strategies are registered (they may already be registered
        # from previous imports, which is fine - we just verify they exist)
        from src.connectors.strategies.registry import (
            initialization_strategy_registry,
        )

        # Verify that known strategies are registered (not default strategy)
        # We check by getting the strategy and verifying it's not the default
        gemini_strategy = initialization_strategy_registry.get_strategy("gemini")
        anthropic_strategy = initialization_strategy_registry.get_strategy("anthropic")
        openrouter_strategy = initialization_strategy_registry.get_strategy(
            "openrouter"
        )

        # Verify strategies augment config (default strategy just returns copy)
        test_config = {"api_key": "test-key"}

        gemini_result = gemini_strategy.augment_init_config(test_config.copy())
        assert "key_name" in gemini_result
        assert gemini_result["key_name"] == "gemini"

        anthropic_result = anthropic_strategy.augment_init_config(test_config.copy())
        assert "key_name" in anthropic_result
        assert anthropic_result["key_name"] == "anthropic"

        openrouter_result = openrouter_strategy.augment_init_config(test_config.copy())
        assert "key_name" in openrouter_result
        assert openrouter_result["key_name"] == "openrouter"

        # Verify unknown strategy still returns default
        unknown_strategy = initialization_strategy_registry.get_strategy("unknown")
        unknown_result = unknown_strategy.augment_init_config(test_config.copy())
        assert unknown_result == test_config  # Default strategy returns copy
