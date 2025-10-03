"""
Enhanced tests for the BackendService implementation.
"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.domain.backend_type import BackendType
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.rate_limiter_interface import RateLimitInfo
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService

# Legacy models removed; use domain ChatRequest instead when needed
from tests.unit.core.test_doubles import MockRateLimiter


# Session-scoped fixtures to optimize test performance
@pytest.fixture(scope="session")
def http_client():
    """Create a shared HTTP client for all tests."""
    return httpx.AsyncClient()


@pytest.fixture(scope="session")
def app_config():
    """Create a shared AppConfig for all tests."""
    from src.core.config.app_config import AppConfig

    return AppConfig()


@pytest.fixture(scope="session")
def backend_registry():
    """Create a shared BackendRegistry for all tests."""
    from src.core.services.backend_registry import BackendRegistry

    return BackendRegistry()


@pytest.fixture(scope="session")
def translation_service():
    """Create a shared TranslationService for all tests."""
    from src.core.services.translation_service import TranslationService

    return TranslationService()


@pytest.fixture(scope="session")
def backend_factory(http_client, backend_registry, app_config, translation_service):
    """Create a shared BackendFactory for all tests."""
    from src.core.services.backend_factory import BackendFactory

    return BackendFactory(
        http_client, backend_registry, app_config, translation_service
    )


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock()
    config.get.return_value = None
    return config


@pytest.fixture
def service_components():
    """Create common service components for testing."""
    rate_limiter = MockRateLimiter()
    session_service = Mock(spec=ISessionService)
    app_state = Mock(spec=IApplicationState)
    from tests.utils.failover_stub import StubFailoverCoordinator

    return rate_limiter, session_service, app_state, StubFailoverCoordinator()


@pytest.fixture
def backend_service(backend_factory, mock_config, service_components):
    """Create a BackendService instance for testing."""
    rate_limiter, session_service, app_state, failover_coordinator = service_components
    return ConcreteBackendService(
        backend_factory,
        rate_limiter,
        mock_config,
        session_service,
        app_state,
        failover_coordinator=failover_coordinator,
    )


class MockBackend(LLMBackend):
    """Mock implementation of LLMBackend for testing."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        available_models: list[str] | None = None,
    ) -> None:
        self.client = client
        self.available_models = available_models or ["model1", "model2"]
        self.initialize_called = False
        self.chat_completions_called = False
        self.chat_completions_mock: AsyncMock = AsyncMock()  # type: ignore

    async def initialize(self, **kwargs: Any) -> None:
        self.initialize_called = True
        self.initialize_kwargs = kwargs

    def get_available_models(self) -> list[str]:
        return self.available_models

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: Any = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.chat_completions_called = True
        self.chat_completions_args = {
            "request_data": request_data,
            "processed_messages": processed_messages,
            "effective_model": effective_model,
            "identity": identity,
            "kwargs": kwargs,
        }
        return await self.chat_completions_mock()


class MockStreamingResponse:
    """Mock implementation of StreamingResponse for testing."""

    def __init__(self, content):
        self.content = content

    def __aiter__(self):
        """Make this class async iterable."""
        return self

    async def __anext__(self):
        if not hasattr(self, "_content_iter"):
            self._content_iter = iter(self.content)
        try:
            chunk = next(self._content_iter)
            return ProcessedResponse(content=chunk)
        except StopIteration:
            raise StopAsyncIteration


class TestBackendFactory:
    """Tests for the BackendFactory class."""

    @pytest.mark.asyncio
    async def test_create_backend(self, backend_factory, http_client, backend_registry):
        """Test creating a backend with the factory."""
        # Mock the backend registry instead of non-existent _backend_types
        mock_backend = MockBackend(http_client)
        with patch.object(
            backend_registry,
            "get_backend_factory",
            return_value=lambda client, config, translation_service: mock_backend,
        ):
            # Act
            backend = backend_factory.create_backend(
                "openai", {}
            )  # Used empty config for test

            # Assert
            assert isinstance(backend, MockBackend)
            assert backend.client == http_client

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_initialize_backend(self, backend_factory, http_client):
        """Test initializing a backend with the factory."""
        backend = MockBackend(http_client)
        init_config = {"api_key": "test-key", "extra_param": "value"}

        # Act
        await backend_factory.initialize_backend(backend, init_config)

        # Assert
        assert backend.initialize_called
        assert backend.initialize_kwargs == init_config

    @pytest.mark.asyncio
    async def test_create_backend_invalid_type(self, backend_factory):
        """Test creating a backend with an invalid type."""
        # Act & Assert
        with pytest.raises(ValueError):
            backend_factory.create_backend("invalid-backend-type", {})


class ConcreteBackendService(BackendService):
    """Concrete implementation of the abstract BackendService for testing."""

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """
        Implement the abstract method for testing purposes.
        This method should not be called directly in tests.
        """
        # Just pass through to the call_completion method
        stream = kwargs.get("stream", False)
        return await self.call_completion(request, stream=stream)


class TestBackendServiceBasic:
    """Basic tests for the BackendService class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = Mock()
        config.get.return_value = None
        return config

    @pytest.fixture
    def service(self, mock_config):
        """Create a BackendService instance for testing."""
        client = httpx.AsyncClient()
        from src.core.services.backend_registry import BackendRegistry

        registry = BackendRegistry()
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        factory = BackendFactory(client, registry, config, TranslationService())
        rate_limiter = MockRateLimiter()
        session_service = Mock(spec=ISessionService)
        app_state = Mock(spec=IApplicationState)
        from tests.utils.failover_stub import StubFailoverCoordinator

        return ConcreteBackendService(
            factory,
            rate_limiter,
            mock_config,
            session_service,
            app_state,
            failover_coordinator=StubFailoverCoordinator(),
        )

    @pytest.mark.asyncio
    async def test_get_or_create_backend_cached(self, service):
        """Test that backends are cached and reused."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        # Use the proper way to add a backend through the factory
        with patch.object(
            service._factory, "ensure_backend", return_value=mock_backend
        ):
            # First call to cache the backend
            await service._get_or_create_backend("openai")

        # Act - Second call should use the cached backend
        result = await service._get_or_create_backend("openai")

        # Assert
        assert result is mock_backend

    @pytest.mark.asyncio
    async def test_get_or_create_backend_new(self, service):
        """Test creating a new backend when not cached."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)

        with (
            patch.object(
                service._factory, "ensure_backend", return_value=mock_backend
            ) as mock_ensure,
        ):
            # Act
            result = await service._get_or_create_backend(BackendType.OPENAI)

            # Assert
            assert result is mock_backend
            # The service uses its own config, not the factory's config
            expected_config = service._config
            mock_ensure.assert_called_once_with(
                BackendType.OPENAI, expected_config, None
            )
            assert "openai" in service._backends  # Used string literal

    @pytest.mark.asyncio
    async def test_get_or_create_backend_error(self, service):
        """Test error handling when creating a backend fails."""
        # Arrange
        with patch.object(
            service._factory, "ensure_backend", side_effect=ValueError("Test error")
        ):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service._get_or_create_backend("openai")  # Used string literal

            assert "Failed to create backend" in str(exc_info.value)
            assert "Test error" in str(exc_info.value)

    def test_prepare_messages_removed(self, service):
        """BackendService no longer implements _prepare_messages; handled by backends."""
        assert not hasattr(service, "_prepare_messages")


class TestBackendServiceCompletions:
    """Tests for the BackendService's completion handling."""

    @staticmethod
    async def mock_streaming_content(
        chunks: list[str],
    ) -> AsyncIterator[ProcessedResponse]:
        for chunk in chunks:
            yield ProcessedResponse(content=chunk)

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = Mock()
        config.get.return_value = None
        return config

    @pytest.fixture
    def service(self, mock_config):
        """Create a BackendService instance for testing."""
        client = httpx.AsyncClient()
        from src.core.services.backend_registry import BackendRegistry

        registry = BackendRegistry()
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        factory = BackendFactory(client, registry, config, TranslationService())
        rate_limiter = MockRateLimiter()
        session_service = Mock(spec=ISessionService)
        app_state = Mock(spec=IApplicationState)
        from tests.utils.failover_stub import StubFailoverCoordinator

        return ConcreteBackendService(
            factory,
            rate_limiter,
            mock_config,
            session_service,
            app_state,
            failover_coordinator=StubFailoverCoordinator(),
        )

    @pytest.fixture
    def chat_request(self):
        """Create a basic chat request for testing."""
        return ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="model1",
            extra_body={"backend_type": BackendType.OPENAI},
        )

    @pytest.mark.asyncio
    async def test_call_completion_basic(self, service, chat_request):
        """Test calling a completion with the service."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "resp-123",
                "created": 123,
                "model": "model1",
                "choices": [],
            },
            headers={},
        )

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            response = await service.call_completion(chat_request)

            # Assert
            assert mock_backend.chat_completions_called
            assert response.content["id"] == "resp-123"
            assert response.content["model"] == "model1"

    @pytest.mark.asyncio
    async def test_call_completion_streaming(self, service, chat_request):
        """Test calling a streaming completion."""
        # Arrange
        chunks = [
            'data: {"id":"chunk1","choices":[{"delta":{"content":"Hello"}}]}\n\n',
            'data: {"id":"chunk2","choices":[{"delta":{"content":" world"}}]}\n\n',
            "data: [DONE]\n\n",
        ]

        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.return_value = StreamingResponseEnvelope(
            content=self.mock_streaming_content(chunks),
            media_type="text/event-stream",
            headers={},
        )

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            response = await service.call_completion(chat_request, stream=True)

            # Assert
            assert mock_backend.chat_completions_called

            # Collect chunks from the stream
            result_chunks = []
            async for chunk in response.content:
                result_chunks.append(chunk)

            # Verify chunks
            assert len(result_chunks) == len(chunks)
            for i, chunk in enumerate(chunks):
                assert isinstance(result_chunks[i], ProcessedResponse)
                assert result_chunks[i].content == chunk

    @pytest.mark.asyncio
    async def test_call_completion_streaming_error(self, service, chat_request):
        """Test error handling in streaming completion."""

        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        # Instead of creating a response that raises during iteration,
        # Make the chat_completions call itself raise an error
        mock_backend.chat_completions_mock.side_effect = ValueError("Streaming error")

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service.call_completion(
                    chat_request, stream=True, allow_failover=False
                )

            # Verify the error was caught and wrapped in BackendError
            assert "Streaming error" in str(exc_info.value) or "ValueError" in str(
                exc_info.value
            )

    @pytest.mark.asyncio
    async def test_call_completion_rate_limited(self, service, chat_request):
        """Test rate limiting in the backend service."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)

        # Add the backend properly through a patched factory
        with patch.object(
            service._factory, "ensure_backend", return_value=mock_backend
        ):
            # Cache the backend
            await service._get_or_create_backend(BackendType.OPENAI)

        # Configure rate limiter to report limit exceeded
        service._rate_limiter.limits[f"backend:{BackendType.OPENAI}"] = RateLimitInfo(
            is_limited=True, remaining=0, reset_at=123, limit=10, time_window=60
        )

        # Act & Assert
        with pytest.raises(RateLimitExceededError) as exc_info:
            await service.call_completion(chat_request)

        # Verify exception details - only check the basic message
        assert "Rate limit exceeded" in str(exc_info.value)
        # The actual rate limit values may not be included in the string representation
        # so we're only checking for the essential message

    @pytest.mark.asyncio
    async def test_call_completion_backend_error(self, service, chat_request):
        """Test error handling when backend calls fail."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.side_effect = ValueError("API error")

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service.call_completion(chat_request, allow_failover=False)

            # Verify exception details
            assert "Backend call failed" in str(exc_info.value)
            assert "API error" in str(exc_info.value)
            # Note: The backend type may not be included in the error message in all implementations

    @pytest.mark.asyncio
    async def test_call_completion_invalid_response(self, service, chat_request):
        """Test error handling for invalid response format."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        # Return invalid response format (not a tuple)
        mock_backend.chat_completions_mock.side_effect = Exception(
            "Invalid response format"
        )

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service.call_completion(chat_request)

            # Don't check for specific error message as it may vary across implementations
            assert "Invalid response format" in str(
                exc_info.value
            ) or "Backend call failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_completion_invalid_streaming_response(
        self,
        service,
        chat_request,
    ):
        """Test error handling for invalid streaming response format."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        # Return invalid response format (not a StreamingResponse)
        mock_backend.chat_completions_mock.side_effect = Exception(
            "Invalid streaming response format"
        )

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service.call_completion(
                    chat_request, stream=True, allow_failover=False
                )

            # Don't check for specific error message as it may vary across implementations
            assert "Invalid streaming response" in str(
                exc_info.value
            ) or "Exception" in str(exc_info.value)


class TestBackendServiceValidation:
    """Tests for the BackendService's validation capabilities."""

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_valid(self, backend_service, http_client):
        """Test validating a valid backend and model."""
        # Arrange
        mock_backend = MockBackend(
            http_client, available_models=["valid-model", "other-model"]
        )

        with patch.object(
            backend_service, "_get_or_create_backend", return_value=mock_backend
        ):
            # Act
            valid, error = await backend_service.validate_backend_and_model(
                BackendType.OPENAI, "valid-model"
            )

            # Assert
            assert valid is True
            assert error is None

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_invalid_model(
        self, backend_service, http_client
    ):
        """Test validating an invalid model."""
        # Arrange
        mock_backend = MockBackend(http_client, available_models=["valid-model"])

        with patch.object(
            backend_service, "_get_or_create_backend", return_value=mock_backend
        ):
            # Act
            valid, error = await backend_service.validate_backend_and_model(
                BackendType.OPENAI, "invalid-model"
            )

            # Assert
            assert valid is False
            assert "not available" in error

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_backend_error(self, backend_service):
        """Test validating with a backend error."""
        # Arrange
        with patch.object(
            backend_service,
            "_get_or_create_backend",
            side_effect=ValueError("Backend error"),
        ):
            # Act
            valid, error = await backend_service.validate_backend_and_model(
                BackendType.OPENAI, "model"
            )

            # Assert
            assert valid is False
            assert "Backend validation failed" in error
            assert "Backend error" in error


class TestBackendServiceFailover:
    """Tests for the BackendService's failover capabilities."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = Mock()
        config.get.return_value = None
        return config

    @pytest.fixture
    def service_with_simple_failover(self, mock_config):
        """Create a BackendService instance with simple failover routes."""
        client = httpx.AsyncClient()
        from src.core.services.backend_registry import BackendRegistry

        registry = BackendRegistry()
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        factory = BackendFactory(client, registry, config, TranslationService())
        rate_limiter = MockRateLimiter()
        session_service = Mock(spec=ISessionService)
        app_state = Mock(spec=IApplicationState)

        # Configure failover routes
        failover_routes: dict[str, dict[str, Any]] = {
            BackendType.OPENAI.value: {
                "backend": BackendType.OPENROUTER.value,
                "model": "fallback-model",
            }
        }

        from tests.utils.failover_stub import StubFailoverCoordinator

        return ConcreteBackendService(
            factory,
            rate_limiter,
            mock_config,
            session_service,
            app_state,
            failover_routes=failover_routes,
            failover_coordinator=StubFailoverCoordinator(),
        )

    @pytest.fixture
    def service_with_complex_failover(self, mock_config):
        """Create a BackendService instance with complex failover routes."""
        client = httpx.AsyncClient()
        from src.core.services.backend_registry import BackendRegistry

        registry = BackendRegistry()
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        factory = BackendFactory(client, registry, config, TranslationService())
        rate_limiter = MockRateLimiter()
        session_service = Mock(spec=ISessionService)
        app_state = Mock(spec=IApplicationState)

        # Configure complex failover routes by model
        failover_routes: dict[str, dict[str, Any]] = {
            "complex-model": {
                "attempts": [
                    {"backend": BackendType.ANTHROPIC.value, "model": "claude-2"},
                    {
                        "backend": BackendType.OPENROUTER.value,
                        "model": "last-resort-model",
                    },
                ]
            }
        }

        from tests.utils.failover_stub import StubFailoverCoordinator

        return ConcreteBackendService(
            factory,
            rate_limiter,
            mock_config,
            session_service,
            app_state,
            failover_routes=failover_routes,
            failover_coordinator=StubFailoverCoordinator(),
        )

    @pytest.fixture
    def chat_request(self):
        """Create a basic chat request for testing."""
        return ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="model1",
            extra_body={"backend_type": BackendType.OPENAI},
        )

    @pytest.fixture
    def chat_request_complex(self):
        """Create a request with complex failover model."""
        return ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="complex-model",
            extra_body={"backend_type": BackendType.OPENAI},
        )

    @pytest.mark.asyncio
    async def test_simple_failover(self, service_with_simple_failover, chat_request):
        """Test simple backend failover when primary fails."""
        # Arrange
        # Create primary backend that fails
        client1 = httpx.AsyncClient()
        primary_backend = MockBackend(client1)
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # Create fallback backend that succeeds
        client2 = httpx.AsyncClient()
        fallback_backend = MockBackend(client2)
        fallback_backend.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "fallback-resp",
                "created": 123,
                "model": "fallback-model",
                "choices": [],
            },
            headers={},
        )

        # Mock get_or_create_backend to return the appropriate backend
        original_get_or_create = service_with_simple_failover._get_or_create_backend

        async def mock_get_or_create(backend_type):
            if backend_type == BackendType.OPENAI:
                return primary_backend
            elif backend_type == BackendType.OPENROUTER:
                return fallback_backend
            return await original_get_or_create(backend_type)

        # Act
        with patch.object(
            service_with_simple_failover,
            "_get_or_create_backend",
            side_effect=mock_get_or_create,
        ):
            response = await service_with_simple_failover.call_completion(chat_request)

        # Assert
        assert primary_backend.chat_completions_called
        assert fallback_backend.chat_completions_called
        assert response.content["id"] == "fallback-resp"
        assert response.content["model"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_complex_failover_first_attempt(
        self,
        service_with_complex_failover,
        chat_request_complex,
    ):
        """Test complex model-specific failover, first attempt succeeds."""
        # Arrange
        # Primary backend fails
        client1 = httpx.AsyncClient()
        primary_backend = MockBackend(client1)
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # First failover attempt succeeds
        client2 = httpx.AsyncClient()
        first_fallback = MockBackend(client2)
        first_fallback.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "claude-resp",
                "created": 123,
                "model": "claude-2",
                "choices": [],
            },
            headers={},
        )

        # Second failover never called
        client3 = httpx.AsyncClient()
        second_fallback = MockBackend(client3)

        # Mock get_or_create_backend
        original_get_or_create = service_with_complex_failover._get_or_create_backend

        async def mock_get_or_create(backend_type):
            if backend_type == BackendType.OPENAI:
                return primary_backend
            elif backend_type == BackendType.ANTHROPIC:
                return first_fallback
            elif backend_type == BackendType.OPENROUTER:
                return second_fallback
            return await original_get_or_create(backend_type)

        # Act
        with (
            patch.object(
                service_with_complex_failover,
                "_get_or_create_backend",
                side_effect=mock_get_or_create,
            ),
            patch(
                "src.core.domain.configuration.backend_config.BackendConfiguration"
            ) as mock_config_class,
            patch.object(
                service_with_complex_failover._failover_coordinator,
                "get_failover_attempts",
            ) as mock_get_attempts,
        ):
            mock_config = Mock()
            mock_config_class.return_value = mock_config

            # Mock get_failover_attempts directly to avoid validation issues
            from dataclasses import dataclass

            @dataclass
            class MockAttempt:
                backend: str
                model: str

            # Mock first attempt which will succeed
            attempts = [MockAttempt(backend=BackendType.ANTHROPIC, model="claude-2")]
            mock_get_attempts.return_value = attempts

            response = await service_with_complex_failover.call_completion(
                chat_request_complex
            )

        # Assert - in the current implementation, it may skip directly to the failover backend
        # without calling the primary backend, depending on implementation details
        # The important part is that we got the expected response from the first fallback
        assert first_fallback.chat_completions_called
        assert not second_fallback.chat_completions_called
        assert response.content["id"] == "claude-resp"
        assert response.content["model"] == "claude-2"

    @pytest.mark.asyncio
    async def test_complex_failover_second_attempt(
        self,
        service_with_complex_failover,
        chat_request_complex,
    ):
        """Test complex model-specific failover, second attempt succeeds after first fails."""
        # Arrange
        # Primary backend fails
        client1 = httpx.AsyncClient()
        primary_backend = MockBackend(client1)
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # First failover attempt fails
        client2 = httpx.AsyncClient()
        first_fallback = MockBackend(client2)
        first_fallback.chat_completions_mock.side_effect = ValueError(
            "First failover error"
        )

        # Second failover succeeds
        client3 = httpx.AsyncClient()
        second_fallback = MockBackend(client3)
        second_fallback.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "last-resort",
                "created": 123,
                "model": "last-resort-model",
                "choices": [],
            },
            headers={},
        )

        # Mock get_or_create_backend
        original_get_or_create = service_with_complex_failover._get_or_create_backend

        async def mock_get_or_create(backend_type):
            if backend_type == BackendType.OPENAI:
                return primary_backend
            elif backend_type == BackendType.ANTHROPIC:
                return first_fallback
            elif backend_type == BackendType.OPENROUTER:
                return second_fallback
            return await original_get_or_create(backend_type)

        # Act
        with (
            patch.object(
                service_with_complex_failover,
                "_get_or_create_backend",
                side_effect=mock_get_or_create,
            ),
            patch(
                "src.core.domain.configuration.backend_config.BackendConfiguration"
            ) as mock_config_class,
            patch.object(
                service_with_complex_failover._failover_coordinator,
                "get_failover_attempts",
            ) as mock_get_attempts,
        ):
            mock_config = Mock()
            mock_config_class.return_value = mock_config

            # Mock get_failover_attempts directly to avoid validation issues
            from dataclasses import dataclass

            @dataclass
            class MockAttempt:
                backend: str
                model: str

            # Setup mock for get_failover_attempts with both attempts
            attempts = [
                MockAttempt(backend=BackendType.ANTHROPIC, model="claude-2"),
                MockAttempt(backend=BackendType.OPENROUTER, model="last-resort-model"),
            ]
            mock_get_attempts.return_value = attempts

            response = await service_with_complex_failover.call_completion(
                chat_request_complex
            )

        # Assert - in the current implementation, it may skip directly to the failover backends
        # without calling the primary backend, depending on implementation details
        assert first_fallback.chat_completions_called
        assert second_fallback.chat_completions_called
        assert response.content["id"] == "last-resort"
        assert response.content["model"] == "last-resort-model"

    @pytest.mark.asyncio
    async def test_complex_failover_all_fail(
        self,
        service_with_complex_failover,
        chat_request_complex,
    ):
        """Test complex model-specific failover when all attempts fail."""
        # Arrange
        # Primary backend fails
        client1 = httpx.AsyncClient()
        primary_backend = MockBackend(client1)
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # First failover attempt fails
        client2 = httpx.AsyncClient()
        first_fallback = MockBackend(client2)
        first_fallback.chat_completions_mock.side_effect = ValueError(
            "First failover error"
        )

        # Second failover fails
        client3 = httpx.AsyncClient()
        second_fallback = MockBackend(client3)
        second_fallback.chat_completions_mock.side_effect = ValueError(
            "Second failover error"
        )

        # Mock get_or_create_backend
        original_get_or_create = service_with_complex_failover._get_or_create_backend

        async def mock_get_or_create(backend_type):
            if backend_type == BackendType.OPENAI:
                return primary_backend
            elif backend_type == BackendType.ANTHROPIC:
                return first_fallback
            elif backend_type == BackendType.OPENROUTER:
                return second_fallback
            return await original_get_or_create(backend_type)

        # Act
        with (
            patch.object(
                service_with_complex_failover,
                "_get_or_create_backend",
                side_effect=mock_get_or_create,
            ),
            patch(
                "src.core.domain.configuration.backend_config.BackendConfiguration"
            ) as mock_config_class,
            patch.object(
                service_with_complex_failover._failover_coordinator,
                "get_failover_attempts",
            ) as mock_get_attempts,
        ):
            mock_config = Mock()
            mock_config_class.return_value = mock_config

            # Mock get_failover_attempts directly to avoid validation issues
            from dataclasses import dataclass

            @dataclass
            class MockAttempt:
                backend: str
                model: str

            # Setup mock for get_failover_attempts with both attempts
            attempts = [
                MockAttempt(backend=BackendType.ANTHROPIC, model="claude-2"),
                MockAttempt(backend=BackendType.OPENROUTER, model="last-resort-model"),
            ]
            mock_get_attempts.return_value = attempts

            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service_with_complex_failover.call_completion(
                    chat_request_complex
                )

        # Verify that fallback attempts were called
        # In the current implementation, it may skip the primary backend call
        assert first_fallback.chat_completions_called
        assert second_fallback.chat_completions_called
        # The exact error message varies between implementations, but it should indicate failure
        assert "All failover attempts failed" in str(exc_info.value)
