"""
Behavior specification tests for Application State Service.

These tests follow BDD principles to specify the expected behavior of the application
state management system as defined in architecture requirements. They use Given-When-Then
structure to clearly specify behavior requirements rather than just validating
implementation details.

Key behaviors specified:
1. State persistence across different providers (local vs external)
2. State consistency and synchronization between providers
3. Type validation and error handling for state operations
4. Feature flag management and dynamic configuration
5. Backend management and failover configuration
6. Concurrent access and thread safety
7. State provider switching and migration
"""

import asyncio
import threading
from unittest.mock import Mock

import pytest
from src.core.services.application_state_service import ApplicationStateService


class TestStateProviderBehavior:
    """
    Behavior specifications for state provider management as defined in architecture.

    Given: An application state service with different provider configurations
    When: State operations are performed
    Then: State should be correctly managed across different providers
    """

    def test_local_state_provider_initialization(self):
        """
        Given: An application state service initialized without a provider
        When: State operations are performed
        Then: State should be stored locally and retrievable
        """
        # Given
        service = ApplicationStateService()

        # When
        service.set_command_prefix("/test")
        service.set_api_key_redaction_enabled(True)
        service.set_disable_interactive_commands(False)

        # Then
        assert service.get_command_prefix() == "/test"
        assert service.get_api_key_redaction_enabled() is True
        assert service.get_disable_interactive_commands() is False

    def test_external_state_provider_integration(self):
        """
        Given: An application state service with an external state provider
        When: State operations are performed
        Then: State should be stored in both local and external providers
        """
        # Given
        mock_provider = Mock()
        service = ApplicationStateService(mock_provider)

        # When
        service.set_command_prefix("/external")
        service.set_api_key_redaction_enabled(True)

        # Then
        # Verify external provider was called
        assert mock_provider.command_prefix == "/external"
        assert mock_provider.api_key_redaction_enabled is True

        # Verify local state is also maintained
        assert service.get_command_prefix() == "/external"
        assert service.get_api_key_redaction_enabled() is True

    def test_state_provider_switching_behavior(self):
        """
        Given: An application state service with existing local state
        When: A new state provider is set
        Then: Existing state should remain accessible and new state should go to both providers
        """
        # Given
        service = ApplicationStateService()
        service.set_command_prefix("/original")
        service.set_api_key_redaction_enabled(True)

        # When
        new_provider = Mock()
        # Configure the Mock to properly simulate state provider behavior
        # The Mock should not have command_prefix initially to test fallback to local state
        del new_provider.command_prefix  # Ensure attribute doesn't exist initially
        del (
            new_provider.api_key_redaction_enabled
        )  # Ensure attribute doesn't exist initially

        service.set_state_provider(new_provider)
        service.set_disable_commands(True)  # Set new state after provider switch

        # Then
        # Original state should still be accessible from local storage (provider doesn't have these attributes)
        assert service.get_command_prefix() == "/original"
        assert service.get_api_key_redaction_enabled() is True

        # New state should be in both providers
        assert service.get_disable_commands() is True
        assert new_provider.disable_commands is True

    def test_state_provider_priority_behavior(self):
        """
        Given: Both local and external state providers have different values
        When: State is retrieved
        Then: External provider values should take precedence over local values
        """
        # Given
        mock_provider = Mock()
        mock_provider.command_prefix = "/provider"
        mock_provider.api_key_redaction_enabled = False

        service = ApplicationStateService(mock_provider)
        # Set different values in local state
        service._local_state["command_prefix"] = "/local"
        service._local_state["api_key_redaction_enabled"] = True

        # When
        retrieved_prefix = service.get_command_prefix()
        retrieved_redaction = service.get_api_key_redaction_enabled()

        # Then
        # Provider values should take precedence
        assert retrieved_prefix == "/provider"
        assert retrieved_redaction is False

    def test_missing_provider_attribute_handling(self):
        """
        Given: An external state provider without expected attributes
        When: State operations are performed
        Then: Operations should fall back to local state gracefully
        """
        # Given
        incomplete_provider = Mock()
        # Only set some attributes, leave others missing
        incomplete_provider.command_prefix = "/incomplete"
        # api_key_redaction_enabled is missing

        service = ApplicationStateService(incomplete_provider)

        # When
        service.set_api_key_redaction_enabled(True)  # Should go to local state
        service.set_command_prefix("/override")  # Should go to both

        # Then
        assert service.get_command_prefix() == "/override"
        assert service.get_api_key_redaction_enabled() is True
        assert incomplete_provider.command_prefix == "/override"
        # Missing attribute should not cause errors


class TestStateConsistencyBehavior:
    """
    Behavior specifications for state consistency and synchronization.

    Given: Multiple state operations performed rapidly
    When: State is accessed from different contexts
    Then: State should remain consistent and synchronized
    """

    def test_boolean_state_consistency(self):
        """
        Given: Various boolean state configurations
        When: State is set and retrieved
        Then: Boolean values should maintain type consistency
        """
        # Given
        service = ApplicationStateService()

        # When - Test various boolean configurations
        test_cases = [
            (True, True),
            (False, False),
            (1, True),  # Truthy integer
            (0, False),  # Falsy integer
            ("true", True),  # Truthy string
            ("", False),  # Falsy string
            (None, False),  # None should be falsy
        ]

        for input_val, expected in test_cases:
            # When
            service.set_api_key_redaction_enabled(input_val)
            service.set_disable_interactive_commands(input_val)
            service.set_disable_commands(input_val)

            # Then
            assert service.get_api_key_redaction_enabled() == expected
            assert service.get_disable_interactive_commands() == expected
            assert service.get_disable_commands() == expected

    def test_string_state_type_validation(self):
        """
        Given: Various string input types
        When: String state is set and retrieved
        Then: Only valid string values should be returned
        """
        # Given
        service = ApplicationStateService()

        # When
        test_cases = [
            ("valid_string", "valid_string"),
            (123, None),  # Invalid type should return None
            (None, None),
            ([], None),
            ({}, None),
            ("", ""),  # Empty string is valid
        ]

        for input_val, expected in test_cases:
            service.set_command_prefix(input_val)
            result = service.get_command_prefix()
            assert result == expected, f"Failed for input: {input_val}"

    def test_complex_state_type_handling(self):
        """
        Given: Complex data structures as state values
        When: State is set and retrieved
        Then: Complex types should be handled appropriately
        """
        # Given
        service = ApplicationStateService()

        # Test model defaults (dict)
        model_defaults = {"temperature": 0.7, "max_tokens": 1000, "model": "gpt-4"}

        # When
        service.set_model_defaults(model_defaults)
        service.set_functional_backends(["openai", "gemini"])
        service.set_backend_type("openai")

        # Then
        retrieved_defaults = service.get_model_defaults()
        retrieved_backends = service.get_functional_backends()
        retrieved_backend_type = service.get_backend_type()

        assert retrieved_defaults == model_defaults
        assert retrieved_backends == ["openai", "gemini"]
        assert retrieved_backend_type == "openai"

    def test_failover_routes_state_management(self):
        """
        Given: Complex failover route configurations
        When: Routes are set and retrieved
        Then: Route configurations should be properly normalized and maintained
        """
        # Given
        service = ApplicationStateService()

        # When - Set routes as list (common format)
        routes_list = [
            {"name": "primary", "backend": "openai", "model": "gpt-4", "priority": 1},
            {
                "name": "secondary",
                "backend": "gemini",
                "model": "gemini-pro",
                "priority": 2,
            },
        ]

        service.set_failover_routes(routes_list)

        # Then
        retrieved_routes = service.get_failover_routes()
        assert retrieved_routes is not None
        assert len(retrieved_routes) == 2

        # When - Set individual route
        service.set_failover_route(
            "tertiary", {"backend": "anthropic", "model": "claude-3", "priority": 3}
        )

        # Then
        updated_routes = service.get_failover_routes()
        assert len(updated_routes) == 3


class TestConcurrentStateAccessBehavior:
    """
    Behavior specifications for concurrent state access and thread safety.

    Given: Multiple threads accessing state simultaneously
    When: State operations are performed concurrently
    Then: Operations should complete safely without data corruption
    """

    def test_concurrent_read_write_safety(self):
        """
        Given: Multiple threads performing read/write operations
        When: Operations are performed simultaneously
        Then: All operations should complete without race conditions
        """
        # Given
        service = ApplicationStateService()
        num_threads = 10
        operations_per_thread = 100

        def worker_thread(thread_id: int):
            """Worker function that performs state operations."""
            for i in range(operations_per_thread):
                # Perform mixed read/write operations
                service.set_api_key_redaction_enabled(i % 2 == 0)
                service.set_disable_interactive_commands(thread_id % 2 == 0)

                # Read state
                redaction = service.get_api_key_redaction_enabled()
                disable_interactive = service.get_disable_interactive_commands()

                # Verify state is consistent (should be boolean)
                assert isinstance(redaction, bool)
                assert isinstance(disable_interactive, bool)

        # When
        threads = []
        for thread_id in range(num_threads):
            thread = threading.Thread(target=worker_thread, args=(thread_id,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Then - Service should still be functional
        assert isinstance(service.get_api_key_redaction_enabled(), bool)
        assert isinstance(service.get_disable_interactive_commands(), bool)

    def test_concurrent_provider_switching(self):
        """
        Given: Multiple threads switching state providers
        When: Provider switching happens during state operations
        Then: State operations should remain consistent
        """
        # Given
        service = ApplicationStateService()
        providers = [Mock() for _ in range(5)]

        def state_worker():
            """Worker that performs state operations."""
            for i in range(50):
                service.set_command_prefix(f"/thread_{i}")
                prefix = service.get_command_prefix()
                assert prefix is not None

        def provider_switcher():
            """Worker that switches providers."""
            for _i, provider in enumerate(providers):
                service.set_state_provider(provider)

        # When
        threads = [
            threading.Thread(target=state_worker),
            threading.Thread(target=state_worker),
            threading.Thread(target=provider_switcher),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Then - Final state should be consistent
        final_prefix = service.get_command_prefix()
        assert final_prefix is not None
        assert isinstance(final_prefix, str)

    def test_async_concurrent_access(self):
        """
        Given: Multiple async coroutines accessing state
        When: Operations are performed concurrently
        Then: State should remain consistent across async operations
        """
        # Given
        service = ApplicationStateService()

        async def async_worker(worker_id: int):
            """Async worker that performs state operations."""
            for i in range(50):
                service.set_functional_backends([f"backend_{worker_id}_{i}"])
                service.set_backend_type(f"type_{worker_id}")

                backends = service.get_functional_backends()
                backend_type = service.get_backend_type()

                assert isinstance(backends, list)
                assert isinstance(backend_type, str) or backend_type is None

        # When
        async def run_concurrent_workers():
            tasks = [async_worker(i) for i in range(5)]
            await asyncio.gather(*tasks)

        # Run the async test
        asyncio.run(run_concurrent_workers())

        # Then - Service should still be functional
        backends = service.get_functional_backends()
        assert isinstance(backends, list)


class TestFeatureFlagBehavior:
    """
    Behavior specifications for feature flag management and dynamic configuration.

    Given: Various feature flag configurations
    When: Feature flags are toggled and checked
    Then: Feature state should be accurately reflected
    """

    def test_failover_strategy_feature_flag(self):
        """
        Given: Failover strategy feature flag
        When: Flag is enabled/disabled
        Then: Strategy usage should reflect the flag state
        """
        # Given
        service = ApplicationStateService()

        # When/Then - Test default state
        assert service.get_use_failover_strategy() is False

        # When - Enable failover strategy
        service.set_use_failover_strategy(True)

        # Then
        assert service.get_use_failover_strategy() is True

        # When - Disable failover strategy
        service.set_use_failover_strategy(False)

        # Then
        assert service.get_use_failover_strategy() is False

    def test_streaming_pipeline_feature_flag(self):
        """
        Given: Streaming pipeline feature flag
        When: Flag is toggled
        Then: Pipeline usage should reflect the flag state
        """
        # Given
        service = ApplicationStateService()

        # When/Then - Test default state
        assert service.get_use_streaming_pipeline() is False

        # When - Enable streaming pipeline
        service.set_use_streaming_pipeline(True)

        # Then
        assert service.get_use_streaming_pipeline() is True

        # When - Disable streaming pipeline
        service.set_use_streaming_pipeline(False)

        # Then
        assert service.get_use_streaming_pipeline() is False

    def test_feature_flag_persistence_across_providers(self):
        """
        Given: Feature flags set with different providers
        When: Providers are switched
        Then: Feature flag state should be consistent
        """
        # Given
        service = ApplicationStateService()
        service.set_use_failover_strategy(True)
        service.set_use_streaming_pipeline(True)

        # When - Switch to external provider
        external_provider = Mock()
        service.set_state_provider(external_provider)

        # Set additional feature flags
        service.set_use_failover_strategy(False)

        # Then - Check state consistency
        assert service.get_use_failover_strategy() is False
        assert (
            service.get_use_streaming_pipeline() is True
        )  # Should maintain previous state
        assert hasattr(external_provider, "PROXY_USE_FAILOVER_STRATEGY")
        assert external_provider.PROXY_USE_FAILOVER_STRATEGY is False

    def test_generic_setting_management(self):
        """
        Given: Generic setting key-value pairs
        When: Settings are set and retrieved
        Then: Settings should be properly stored and retrieved with correct types
        """
        # Given
        service = ApplicationStateService()

        # When - Set various types of settings
        test_settings = {
            "string_setting": "test_value",
            "int_setting": 42,
            "bool_setting": True,
            "float_setting": 3.14,
            "list_setting": [1, 2, 3],
            "dict_setting": {"key": "value"},
            "none_setting": None,
        }

        for key, value in test_settings.items():
            service.set_setting(key, value)

        # Then - Retrieve and verify settings
        for key, expected_value in test_settings.items():
            retrieved_value = service.get_setting(key)
            assert retrieved_value == expected_value, f"Failed for key: {key}"

        # Test default value behavior
        assert service.get_setting("nonexistent", "default") == "default"
        assert service.get_setting("nonexistent") is None

    def test_backend_configuration_management(self):
        """
        Given: Backend configuration settings
        When: Backend settings are modified
        Then: Configuration should be properly maintained
        """
        # Given
        service = ApplicationStateService()
        mock_backend = Mock()
        mock_backend.name = "test_backend"
        mock_backend.api_key = "test_key"

        # When
        service.set_backend(mock_backend)
        service.set_backend_type("openai")
        service.set_functional_backends(["openai", "gemini", "anthropic"])

        # Then
        retrieved_backend = service.get_backend()
        retrieved_type = service.get_backend_type()
        retrieved_backends = service.get_functional_backends()

        assert retrieved_backend == mock_backend
        assert retrieved_type == "openai"
        assert retrieved_backends == ["openai", "gemini", "anthropic"]


class TestErrorHandlingAndResilienceBehavior:
    """
    Behavior specifications for error handling and system resilience.

    Given: Various error conditions and edge cases
    When: State operations encounter these conditions
    Then: System should handle gracefully without crashes
    """

    def test_provider_attribute_error_handling(self):
        """
        Given: A state provider that raises attribute access errors
        When: State operations are performed
        Then: Operations should fall back to local state without crashing
        """

        # Given
        class FailingProvider:
            def __getattr__(self, name):
                if name == "command_prefix":
                    raise AttributeError("Simulated access error")
                return super().__getattribute__(name)

        failing_provider = FailingProvider()
        service = ApplicationStateService(failing_provider)

        # When - Operations that should trigger provider access
        service.set_command_prefix("/test")  # This should trigger the error
        prefix = service.get_command_prefix()  # This should fall back to local

        # Then
        assert prefix == "/test"

    def test_corrupted_state_recovery(self):
        """
        Given: Corrupted or invalid state in local storage
        When: State operations are performed
        Then: Service should recover and continue functioning
        """
        # Given
        service = ApplicationStateService()

        # Simulate corrupted state by directly manipulating internal storage
        service._local_state["command_prefix"] = object()  # Invalid object
        service._local_state["api_key_redaction_enabled"] = "not_a_boolean"

        # When - Operations should handle corruption gracefully
        service.set_command_prefix("/recovered")
        service.set_api_key_redaction_enabled(True)

        # Then
        assert service.get_command_prefix() == "/recovered"
        assert service.get_api_key_redaction_enabled() is True

    def test_malformed_failover_routes_handling(self):
        """
        Given: Malformed failover route configurations
        When: Routes are processed
        Then: Malformed data should be handled gracefully
        """
        # Given
        service = ApplicationStateService()

        # Test various malformed route configurations
        malformed_routes = [
            # Missing name field
            {"backend": "openai", "model": "gpt-4"},
            # Invalid structure
            "not_a_dict",
            # Empty dict
            {},
            # Valid route mixed with invalid
            {"name": "valid", "backend": "test"},
            None,
        ]

        # When/Then - Should not crash
        for route_config in malformed_routes:
            try:
                if route_config and isinstance(route_config, dict):
                    service.set_failover_routes([route_config])
                retrieved = service.get_failover_routes()
                # Should return None or valid data, not crash
                assert retrieved is None or isinstance(retrieved, list)
            except Exception as e:
                pytest.fail(f"Failed to handle malformed route {route_config}: {e}")

    def test_type_conversion_edge_cases(self):
        """
        Given: Edge cases for type conversion in state operations
        When: Various input types are provided
        Then: Type conversion should handle edge cases safely
        """
        # Given
        service = ApplicationStateService()

        # Test edge cases for boolean conversion
        edge_cases = [
            # Complex objects
            ({"key": "value"}, True),  # Dict is truthy
            ([], False),  # Empty list is falsy
            ([1, 2, 3], True),  # Non-empty list is truthy
            # String edge cases
            ("False", True),  # String "False" is truthy
            ("0", True),  # String "0" is truthy
            # Number edge cases
            (-1, True),  # Negative numbers are truthy
            (0.0, False),  # Zero float is falsy
            (0.1, True),  # Non-zero float is truthy
        ]

        for input_val, expected in edge_cases:
            # When
            service.set_api_key_redaction_enabled(input_val)
            result = service.get_api_key_redaction_enabled()

            # Then
            assert (
                result == expected
            ), f"Failed for input: {input_val} (expected {expected}, got {result})"

    def test_memory_leak_prevention(self):
        """
        Given: Long-running service with many state changes
        When: State is repeatedly modified
        Then: Memory usage should not grow unbounded
        """
        # Given
        service = ApplicationStateService()

        # When - Perform many state operations
        initial_memory = len(service._local_state)

        for i in range(1000):
            service.set_setting(f"temp_key_{i}", f"value_{i}")
            service.set_functional_backends([f"backend_{j}" for j in range(i % 10)])
            service.get_setting(f"temp_key_{i}")

        # Clean up some settings
        for i in range(500):
            if f"temp_key_{i}" in service._local_state:
                del service._local_state[f"temp_key_{i}"]

        # Then - Memory should be controlled (this is a basic check)
        final_memory = len(service._local_state)

        # Should not have grown excessively (allowing for some legitimate growth)
        assert final_memory < initial_memory + 1000  # Reasonable bound

        # Service should still be functional
        assert service.get_setting("temp_key_999") == "value_999"
        assert isinstance(service.get_functional_backends(), list)
