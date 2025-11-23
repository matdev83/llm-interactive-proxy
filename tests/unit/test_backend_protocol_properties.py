"""
Property-based tests for StreamProducer protocol conformance.

Feature: streaming-pipeline-refactor, Property 5: Protocol conformance

This module tests that all backend connectors properly implement the
StreamProducer protocol as defined in the streaming contracts.
"""

import inspect
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.connectors.anthropic import AnthropicBackend
from src.connectors.gemini import GeminiBackend
from src.connectors.openai import OpenAIConnector


# Test data generators
@st.composite
def backend_instances(draw: Any) -> Any:
    """Generate backend instances for testing."""
    backend_type = draw(st.sampled_from(["openai", "anthropic", "gemini"]))
    return backend_type


class TestStreamProducerProtocolConformance:
    """Test that backends conform to StreamProducer protocol.

    Property 5: Protocol conformance
    For any backend that implements streaming, it should implement all
    required methods of the StreamProducer protocol.

    Validates: Requirements 1.5
    """

    @pytest.mark.parametrize(
        "backend_class,provider_name",
        [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ],
    )
    def test_backend_has_stream_completion_method(
        self, backend_class: type, provider_name: str
    ) -> None:
        """Test that backend has stream_completion method.

        Property 5: Protocol conformance
        Feature: streaming-pipeline-refactor, Property 5: Protocol conformance

        For any backend that implements streaming, it should have a
        stream_completion method that matches the StreamProducer protocol.
        """
        # Verify the method exists
        assert hasattr(
            backend_class, "stream_completion"
        ), f"{backend_class.__name__} missing stream_completion method"

        # Verify it's an async generator function (async def ... -> AsyncGenerator)
        method = backend_class.stream_completion
        assert inspect.isasyncgenfunction(
            method
        ), f"{backend_class.__name__}.stream_completion must be async generator"

        # Verify signature matches protocol
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())

        # Should have 'self' and 'request' parameters
        assert (
            "self" in params
        ), f"{backend_class.__name__}.stream_completion missing 'self' parameter"
        assert (
            "request" in params
        ), f"{backend_class.__name__}.stream_completion missing 'request' parameter"

    @pytest.mark.parametrize(
        "backend_class,provider_name",
        [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ],
    )
    def test_backend_has_get_provider_name_method(
        self, backend_class: type, provider_name: str
    ) -> None:
        """Test that backend has get_provider_name method.

        Property 5: Protocol conformance
        Feature: streaming-pipeline-refactor, Property 5: Protocol conformance

        For any backend that implements streaming, it should have a
        get_provider_name method that returns the correct provider name.
        """
        # Verify the method exists
        assert hasattr(
            backend_class, "get_provider_name"
        ), f"{backend_class.__name__} missing get_provider_name method"

        # Verify it's a regular method (not async)
        method = backend_class.get_provider_name
        assert not inspect.iscoroutinefunction(
            method
        ), f"{backend_class.__name__}.get_provider_name should not be async"

        # Verify signature matches protocol
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())

        # Should only have 'self' parameter
        assert (
            "self" in params
        ), f"{backend_class.__name__}.get_provider_name missing 'self' parameter"
        assert (
            len(params) == 1
        ), f"{backend_class.__name__}.get_provider_name should only have 'self' parameter"

    @pytest.mark.parametrize(
        "backend_class,expected_provider",
        [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ],
    )
    def test_get_provider_name_returns_correct_value(
        self,
        backend_class: type,
        expected_provider: str,
        mock_client: Any,
        mock_config: Any,
    ) -> None:
        """Test that get_provider_name returns the correct provider name.

        Property 5: Protocol conformance
        Feature: streaming-pipeline-refactor, Property 5: Protocol conformance

        For any backend, get_provider_name should return the correct
        provider identifier string.
        """
        # Create a minimal instance (may need mocking for dependencies)
        # This test verifies the return value without full initialization
        try:
            # Try to create instance with minimal dependencies
            if backend_class == OpenAIConnector:
                from unittest.mock import Mock

                from src.core.services.translation_service import TranslationService

                mock_translation = Mock(spec=TranslationService)
                instance = backend_class(
                    client=mock_client,
                    config=mock_config,
                    translation_service=mock_translation,
                )
            else:
                from unittest.mock import Mock

                from src.core.services.translation_service import TranslationService

                mock_translation = Mock(spec=TranslationService)
                instance = backend_class(
                    client=mock_client,
                    config=mock_config,
                    translation_service=mock_translation,
                )

            # Call get_provider_name
            provider_name = instance.get_provider_name()

            # Verify it returns the expected string
            assert isinstance(
                provider_name, str
            ), f"get_provider_name should return str, got {type(provider_name)}"
            assert (
                provider_name == expected_provider
            ), f"Expected '{expected_provider}', got '{provider_name}'"

        except Exception as e:
            pytest.fail(
                f"Failed to test get_provider_name for {backend_class.__name__}: {e}"
            )

    @given(backend_type=st.sampled_from(["openai", "anthropic", "gemini"]))
    @settings(max_examples=10)
    def test_protocol_conformance_property(self, backend_type: str) -> None:
        """Property test: All backends conform to StreamProducer protocol.

        Property 5: Protocol conformance
        Feature: streaming-pipeline-refactor, Property 5: Protocol conformance

        For any backend that implements streaming, it should implement all
        required methods of the StreamProducer protocol with correct signatures.

        Validates: Requirements 1.5
        """
        # Map backend type to class
        backend_map = {
            "openai": OpenAIConnector,
            "anthropic": AnthropicBackend,
            "gemini": GeminiBackend,
        }

        backend_class = backend_map[backend_type]

        # Check that the class has all required protocol methods
        protocol_methods = {
            "stream_completion": True,  # Should be async
            "get_provider_name": False,  # Should be sync
        }

        for method_name, should_be_async in protocol_methods.items():
            # Verify method exists
            assert hasattr(
                backend_class, method_name
            ), f"{backend_class.__name__} missing {method_name} method"

            method = getattr(backend_class, method_name)

            # Verify async/sync as expected
            if should_be_async:
                # stream_completion should be an async generator function
                is_async_gen = inspect.isasyncgenfunction(method)
                assert (
                    is_async_gen
                ), f"{backend_class.__name__}.{method_name} should be async generator"
            else:
                # get_provider_name should be a regular sync function
                is_async = inspect.iscoroutinefunction(
                    method
                ) or inspect.isasyncgenfunction(method)
                assert (
                    not is_async
                ), f"{backend_class.__name__}.{method_name} should not be async"

    def test_all_backends_implement_protocol(self) -> None:
        """Test that all backend classes implement the StreamProducer protocol.

        Property 5: Protocol conformance
        Feature: streaming-pipeline-refactor, Property 5: Protocol conformance

        This test verifies that all known backend connectors implement
        the required methods of the StreamProducer protocol.

        Validates: Requirements 1.5
        """
        backends = [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ]

        for backend_class, _provider_name in backends:
            # Check stream_completion method
            assert hasattr(backend_class, "stream_completion"), (
                f"{backend_class.__name__} must implement stream_completion method "
                f"from StreamProducer protocol"
            )

            # Check get_provider_name method
            assert hasattr(backend_class, "get_provider_name"), (
                f"{backend_class.__name__} must implement get_provider_name method "
                f"from StreamProducer protocol"
            )

            # Verify stream_completion is async generator
            assert inspect.isasyncgenfunction(
                backend_class.stream_completion
            ), f"{backend_class.__name__}.stream_completion must be async generator"

            # Verify get_provider_name is not async
            assert not inspect.iscoroutinefunction(
                backend_class.get_provider_name
            ), f"{backend_class.__name__}.get_provider_name must be sync"


@pytest.fixture
def mock_client() -> Any:
    """Provide a mock HTTP client for testing."""
    from unittest.mock import AsyncMock, Mock

    mock = Mock()
    mock.get = AsyncMock()
    mock.post = AsyncMock()
    mock.build_request = Mock()
    mock.send = AsyncMock()
    return mock


@pytest.fixture
def mock_config() -> Any:
    """Provide a mock config for testing."""
    from unittest.mock import Mock

    mock = Mock()
    mock.disable_health_checks = False
    return mock
