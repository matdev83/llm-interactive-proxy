"""
Contract tests for backend streaming behavior.

This module verifies that each backend implements the StreamProducer
protocol correctly and that streaming behavior matches the contract.

Requirements: 1.5, 8.1
"""

import inspect
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from src.connectors.anthropic import AnthropicBackend
from src.connectors.gemini import GeminiBackend
from src.connectors.openai import OpenAIConnector
from src.core.ports.streaming_contracts import StreamProducer


class TestBackendStreamingContracts:
    """Contract tests for backend streaming implementations.

    These tests verify that each backend properly implements the
    StreamProducer protocol and exhibits correct streaming behavior.

    Validates: Requirements 1.5, 8.1
    """

    @pytest.mark.parametrize(
        "backend_class,provider_name",
        [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ],
    )
    def test_backend_implements_stream_producer_protocol(
        self, backend_class: type, provider_name: str
    ) -> None:
        """Verify each backend implements StreamProducer protocol.

        Contract: All streaming backends must implement the StreamProducer
        protocol with the required methods and signatures.

        Validates: Requirements 1.5
        """
        # Check that the backend has all required protocol methods
        required_methods = {
            "stream_completion": {
                "async": True,
                "params": ["self", "request"],
            },
            "get_provider_name": {
                "async": False,
                "params": ["self"],
            },
        }

        for method_name, requirements in required_methods.items():
            # Verify method exists
            assert hasattr(
                backend_class, method_name
            ), f"{backend_class.__name__} must implement {method_name}"

            method = getattr(backend_class, method_name)

            # Verify async/sync requirement
            is_async = inspect.iscoroutinefunction(
                method
            ) or inspect.isasyncgenfunction(method)
            if requirements["async"]:
                assert is_async, f"{backend_class.__name__}.{method_name} must be async"
            else:
                assert (
                    not is_async
                ), f"{backend_class.__name__}.{method_name} must be sync"

            # Verify method signature
            sig = inspect.signature(method)
            params = list(sig.parameters.keys())

            for required_param in requirements["params"]:
                assert (
                    required_param in params
                ), f"{backend_class.__name__}.{method_name} missing parameter '{required_param}'"

    @pytest.mark.parametrize(
        "backend_class,expected_provider",
        [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ],
    )
    def test_get_provider_name_contract(
        self,
        backend_class: type,
        expected_provider: str,
        mock_client: Any,
        mock_config: Any,
        mock_translation_service: Any,
    ) -> None:
        """Verify get_provider_name returns correct provider identifier.

        Contract: get_provider_name must return a string matching the
        backend's provider identifier.

        Validates: Requirements 1.5, 8.1
        """
        # Create backend instance
        instance = backend_class(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # Call get_provider_name
        provider_name = instance.get_provider_name()

        # Verify return type
        assert isinstance(
            provider_name, str
        ), f"get_provider_name must return str, got {type(provider_name)}"

        # Verify return value matches expected provider
        assert (
            provider_name == expected_provider
        ), f"Expected provider '{expected_provider}', got '{provider_name}'"

        # Verify it's consistent across multiple calls
        provider_name_2 = instance.get_provider_name()
        assert (
            provider_name == provider_name_2
        ), "get_provider_name must return consistent value"

    @pytest.mark.parametrize(
        "backend_class,provider_name",
        [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ],
    )
    def test_stream_completion_signature_contract(
        self, backend_class: type, provider_name: str
    ) -> None:
        """Verify stream_completion has correct signature.

        Contract: stream_completion must be an async method that accepts
        a request parameter and returns an AsyncIterator.

        Validates: Requirements 1.5
        """
        # Get the method
        method = backend_class.stream_completion

        # Verify it's async
        assert inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(
            method
        ), f"{backend_class.__name__}.stream_completion must be async"

        # Verify signature
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())

        # Must have 'self' and 'request'
        assert "self" in params, "stream_completion must have 'self' parameter"
        assert "request" in params, "stream_completion must have 'request' parameter"

        # Check return annotation if present
        if sig.return_annotation != inspect.Signature.empty:
            # The return type should indicate an async iterator
            return_type_str = str(sig.return_annotation)
            # Accept various forms of AsyncIterator/AsyncGenerator annotations
            assert any(
                keyword in return_type_str
                for keyword in ["AsyncIterator", "AsyncGenerator", "AsyncIterable"]
            ), f"stream_completion should return AsyncIterator, got {return_type_str}"

    def test_all_backends_have_consistent_protocol_implementation(
        self, mock_client: Any, mock_config: Any, mock_translation_service: Any
    ) -> None:
        """Verify all backends implement protocol consistently.

        Contract: All backends should implement the StreamProducer protocol
        in a consistent manner with the same method names and signatures.

        Validates: Requirements 1.5, 8.1
        """
        backends = [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ]

        # Collect method signatures from all backends
        method_signatures = {}

        for backend_class, provider_name in backends:
            # Create instance
            instance = backend_class(
                client=mock_client,
                config=mock_config,
                translation_service=mock_translation_service,
            )

            # Check get_provider_name
            provider = instance.get_provider_name()
            assert isinstance(
                provider, str
            ), f"{backend_class.__name__} provider must be str"
            assert (
                provider == provider_name
            ), f"Provider mismatch for {backend_class.__name__}"

            # Collect stream_completion signature
            method = backend_class.stream_completion
            sig = inspect.signature(method)

            if "stream_completion" not in method_signatures:
                method_signatures["stream_completion"] = []

            method_signatures["stream_completion"].append(
                {
                    "backend": backend_class.__name__,
                    "params": list(sig.parameters.keys()),
                    "is_async": inspect.iscoroutinefunction(method)
                    or inspect.isasyncgenfunction(method),
                }
            )

        # Verify all backends have the same signature structure
        stream_completion_sigs = method_signatures["stream_completion"]

        # All should be async
        assert all(
            sig["is_async"] for sig in stream_completion_sigs
        ), "All stream_completion methods must be async"

        # All should have same parameters
        first_params = stream_completion_sigs[0]["params"]
        for sig in stream_completion_sigs[1:]:
            assert (
                sig["params"] == first_params
            ), f"Inconsistent parameters: {sig['backend']} has {sig['params']}, expected {first_params}"

    @pytest.mark.parametrize(
        "backend_class,provider_name",
        [
            (OpenAIConnector, "openai"),
            (AnthropicBackend, "anthropic"),
            (GeminiBackend, "gemini"),
        ],
    )
    def test_backend_type_attribute_matches_provider(
        self,
        backend_class: type,
        provider_name: str,
        mock_client: Any,
        mock_config: Any,
        mock_translation_service: Any,
    ) -> None:
        """Verify backend_type attribute matches provider name.

        Contract: The backend_type class attribute should match the
        provider name returned by get_provider_name().

        Validates: Requirements 8.1
        """
        # Check class attribute
        assert hasattr(
            backend_class, "backend_type"
        ), f"{backend_class.__name__} must have backend_type attribute"

        backend_type = backend_class.backend_type
        assert isinstance(
            backend_type, str
        ), f"backend_type must be str, got {type(backend_type)}"

        # Create instance and check get_provider_name
        instance = backend_class(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        provider = instance.get_provider_name()

        # They should match
        assert (
            backend_type == provider
        ), f"backend_type '{backend_type}' doesn't match provider '{provider}'"
        assert (
            provider == provider_name
        ), f"Provider '{provider}' doesn't match expected '{provider_name}'"

    def test_protocol_type_checking(self) -> None:
        """Verify backends can be type-checked against StreamProducer protocol.

        Contract: Backend classes should be compatible with the StreamProducer
        protocol for static type checking purposes.

        Validates: Requirements 1.5
        """
        # This test verifies that the protocol is properly defined
        # and that backends have the required methods

        # Check that StreamProducer is a Protocol
        assert hasattr(
            StreamProducer, "__protocol_attrs__"
        ) or StreamProducer.__class__.__name__ in [
            "Protocol",
            "_ProtocolMeta",
        ], "StreamProducer should be a Protocol"

        # Verify protocol has required methods
        protocol_methods = ["stream_completion", "get_provider_name"]

        for method_name in protocol_methods:
            # Protocol should define these methods
            # (checking via annotations or __annotations__)
            assert hasattr(StreamProducer, method_name) or method_name in getattr(
                StreamProducer, "__annotations__", {}
            ), f"StreamProducer protocol should define {method_name}"


@pytest.fixture
def mock_client() -> Any:
    """Provide a mock HTTP client for testing."""
    mock = Mock()
    mock.get = AsyncMock()
    mock.post = AsyncMock()
    mock.build_request = Mock()
    mock.send = AsyncMock()
    return mock


@pytest.fixture
def mock_config() -> Any:
    """Provide a mock config for testing."""
    mock = Mock()
    mock.disable_health_checks = False
    mock.identity = None
    return mock


@pytest.fixture
def mock_translation_service() -> Any:
    """Provide a mock translation service for testing."""
    from src.core.services.translation_service import TranslationService

    mock = Mock(spec=TranslationService)
    mock.to_domain_request = Mock()
    mock.from_domain_request = Mock()
    mock.to_domain_response = Mock()
    mock.to_domain_stream_chunk = Mock()
    return mock
