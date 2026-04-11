"""Tests for backend initialization strategy registry."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from src.core.common.exceptions import ConfigurationError, LLMProxyError
from src.core.interfaces.backend_initialization_strategy_interface import (
    IBackendInitializationStrategy,
)

logger = logging.getLogger(__name__)


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
        assert gemini_result["key_name"] == "x-goog-api-key"

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

    def test_lazy_auto_discovery_works_on_first_access(self) -> None:
        """Test that lazy auto-discovery mechanism works correctly.

        This test verifies that the global registry's lazy discovery mechanism
        ensures strategies are available when get_strategy() is called, even
        if the registry module was imported without explicit strategy imports.

        Note: This test verifies the lazy discovery mechanism works correctly,
        but does not test complete isolation (strategies may have been discovered
        by other tests). The key verification is that:
        1. Strategies are available via get_strategy() (proving discovery worked)
        2. The _discovered flag is set (proving lazy discovery mechanism ran)
        3. Strategies are properly registered in the registry

        Full isolation testing would require clearing sys.modules which can cause
        deadlocks and test instability, so we verify the mechanism works rather
        than perfect isolation.
        """
        from src.connectors.strategies.registry import (
            initialization_strategy_registry,
        )

        registry = initialization_strategy_registry

        # Verify strategies are available via get_strategy()
        # This proves that lazy discovery has worked (strategies may have been
        # discovered by this test or previous tests, but the mechanism ensures
        # they're available)
        gemini_strategy = registry.get_strategy("gemini")
        test_config = {"api_key": "test-key"}
        gemini_result = gemini_strategy.augment_init_config(test_config.copy())
        assert "key_name" in gemini_result
        assert gemini_result["key_name"] == "x-goog-api-key"

        anthropic_strategy = registry.get_strategy("anthropic")
        anthropic_result = anthropic_strategy.augment_init_config(test_config.copy())
        assert "key_name" in anthropic_result
        assert anthropic_result["key_name"] == "anthropic"

        openrouter_strategy = registry.get_strategy("openrouter")
        openrouter_result = openrouter_strategy.augment_init_config(test_config.copy())
        assert "key_name" in openrouter_result
        assert openrouter_result["key_name"] == "openrouter"

        # Verify strategies are registered in the registry
        with registry._lock:
            assert "gemini" in registry._strategies
            assert "anthropic" in registry._strategies
            assert "openrouter" in registry._strategies

        # Verify that discovery flag is set (proving lazy discovery mechanism ran)
        # This confirms that _auto_discover_strategies() was called at some point
        assert registry._discovered is True


class TestConcurrentStrategyDiscovery:
    """Tests for concurrent strategy discovery race condition fixes.

    Note: These tests verify the event synchronization mechanism works correctly.
    Since strategy modules register to the global registry at import time, we test
    the event mechanism by ensuring threads wait when discovery is in progress.
    """

    def test_concurrent_first_access_race_condition(self) -> None:
        """Test that concurrent threads all receive correct strategies during first discovery.

        This test verifies that the race condition is fixed: when multiple threads
        call get_strategy() concurrently during first discovery, all threads should
        receive the real strategy (not default strategy).

        The test uses an injected mock discovery function that registers strategies
        with a delay to simulate the race condition.
        """
        import threading
        import time

        from src.connectors.strategies.gemini import GeminiInitializationStrategy
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        # Create a fresh registry instance first
        registry = InitializationStrategyRegistry()

        # Mock discovery function that registers to our test registry with delay
        # Define after registry is created so closure captures it correctly
        def mock_discover_with_delay() -> None:
            """Mock discovery that registers strategy to test registry with delay."""
            # Simulate discovery delay (imports take time)
            time.sleep(0.01)
            # Register strategy to our test registry instance
            gemini_strategy = GeminiInitializationStrategy()
            registry.register_strategy("gemini", gemini_strategy)

        # Replace the discovery function with our mock
        registry._discovery_func = mock_discover_with_delay

        # Reset discovery state to simulate first access
        registry._discovered = False
        registry._discovery_event.clear()
        # Clear any strategies that might have been registered
        with registry._lock:
            registry._strategies.clear()

        # Results from concurrent threads
        results: list[dict[str, Any]] = []
        errors: list[Exception] = []
        threads_completed = threading.Event()

        def get_gemini_strategy(thread_id: int) -> None:
            """Get gemini strategy and verify it's not default."""
            try:
                strategy = registry.get_strategy("gemini")
                test_config = {"api_key": "test-key"}
                result = strategy.augment_init_config(test_config.copy())

                # Verify we got the real strategy (not default)
                # Default strategy returns config unmodified, real strategy adds key_name
                assert (
                    "key_name" in result
                ), f"Thread {thread_id} got default strategy instead of gemini strategy"
                assert (
                    result["key_name"] == "x-goog-api-key"
                ), f"Thread {thread_id} got wrong strategy: {result.get('key_name')}"

                results.append(result)
            except Exception as e:
                errors.append(e)
            finally:
                # Signal completion
                if len(results) + len(errors) >= 10:
                    threads_completed.set()

        # Launch multiple threads that all call get_strategy concurrently
        threads = [
            threading.Thread(target=get_gemini_strategy, args=(i,)) for i in range(10)
        ]

        # Start all threads concurrently
        for thread in threads:
            thread.start()

        # Wait for all threads to complete (with timeout)
        threads_completed.wait(timeout=10.0)

        # Wait for all threads to finish
        for thread in threads:
            thread.join(timeout=1.0)
            if thread.is_alive():
                # Thread didn't finish within timeout, mark as potential issue
                logger.warning(f"Thread {thread.name} still alive after join timeout")

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors occurred during concurrent access: {errors}"

        # Verify all threads got correct strategies
        assert len(results) == 10, (
            f"Expected 10 results, got {len(results)}. "
            f"Some threads may have timed out or failed."
        )

        # Verify all results are correct (all should have key_name="x-goog-api-key")
        for i, result in enumerate(results):
            assert "key_name" in result, f"Result {i} missing key_name: {result}"
            assert (
                result["key_name"] == "x-goog-api-key"
            ), f"Result {i} has wrong key_name: {result.get('key_name')}"

        # Verify discovery flag is set
        assert registry._discovered is True

        # Verify discovery event is set
        assert registry._discovery_event.is_set()

    def test_discovery_event_prevents_race(self) -> None:
        """Test that discovery event synchronization prevents race conditions.

        This test verifies that:
        1. Threads waiting on discovery event actually wait
        2. Event is set after discovery completes
        3. All waiting threads proceed after discovery
        """
        import threading
        import time

        from src.connectors.strategies.anthropic import AnthropicInitializationStrategy
        from src.connectors.strategies.registry import (
            InitializationStrategyRegistry,
        )

        # Mock discovery function that registers to our test registry with delay
        def mock_discover_with_delay() -> None:
            """Mock discovery that registers strategy to test registry with delay."""
            time.sleep(0.02)  # Simulate discovery delay
            anthropic_strategy = AnthropicInitializationStrategy()
            registry.register_strategy("anthropic", anthropic_strategy)

        # Create a fresh registry instance with injected mock discovery function
        registry = InitializationStrategyRegistry(
            discovery_func=mock_discover_with_delay
        )

        # Reset discovery state
        registry._discovered = False
        registry._discovery_event.clear()
        with registry._lock:
            registry._strategies.clear()

        # Track when threads proceed
        proceeding_threads: list[int] = []
        discovery_started = threading.Event()

        def get_strategy_with_timing(thread_id: int) -> None:
            """Get strategy and track timing."""
            # Signal that we're about to check discovery
            if thread_id == 0:
                discovery_started.set()

            # Small delay to ensure thread 0 starts discovery first
            if thread_id > 0:
                time.sleep(0.01)

            # This will trigger discovery for thread 0, wait for others
            strategy = registry.get_strategy("anthropic")

            # Verify we got the real strategy
            test_config = {"api_key": "test-key"}
            result = strategy.augment_init_config(test_config.copy())
            assert "key_name" in result
            assert result["key_name"] == "anthropic"

            proceeding_threads.append(thread_id)

        # Launch threads
        threads = [
            threading.Thread(target=get_strategy_with_timing, args=(i,))
            for i in range(5)
        ]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for discovery to start
        discovery_started.wait(timeout=1.0)

        # Give threads time to either discover or wait
        time.sleep(0.05)

        # Verify discovery event is eventually set
        assert registry._discovery_event.wait(
            timeout=5.0
        ), "Discovery event should be set after discovery"

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=2.0)
            if thread.is_alive():
                # Thread didn't finish within timeout, mark as potential issue
                logger.warning(f"Thread {thread.name} still alive after join timeout")

        # Verify all threads completed successfully
        assert (
            len(proceeding_threads) == 5
        ), f"Expected 5 threads to proceed, got {len(proceeding_threads)}"

        # Verify discovery flag is set
        assert registry._discovered is True
