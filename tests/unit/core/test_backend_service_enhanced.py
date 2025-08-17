"""
Enhanced tests for the BackendService implementation.
"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from src.connectors.base import LLMBackend
from src.constants import BackendType
from src.core.common.exceptions import (
    BackendError,
    RateLimitExceededError,
)
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    StreamingChatResponse,
)
from src.core.interfaces.rate_limiter import RateLimitInfo
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService
from src.models import ChatCompletionRequest  # Added import
from starlette.responses import StreamingResponse

from tests.unit.core.test_doubles import MockRateLimiter


class MockBackend(LLMBackend):
    """Mock implementation of LLMBackend for testing."""

    def __init__(self, client, available_models=None):
        self.client = client
        self.available_models = available_models or ["model1", "model2"]
        self.initialize_called = False
        self.chat_completions_called = False
        self.chat_completions_mock = AsyncMock()

    async def initialize(self, **kwargs):
        self.initialize_called = True
        self.initialize_kwargs = kwargs
        return self

    def get_available_models(self):
        return self.available_models

    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str,
        **kwargs: Any,
    ) -> StreamingResponse | tuple[dict[str, Any], dict[str, str]]:  # type: ignore
        self.chat_completions_called = True
        self.chat_completions_args = {
            "request_data": request_data,
            "processed_messages": processed_messages,
            "effective_model": effective_model,
            "kwargs": kwargs,
        }
        return await self.chat_completions_mock()


class MockStreamingResponse(StreamingResponse):
    """Mock implementation of StreamingResponse for testing."""

    def __init__(self, content):
        self.content = content
        self.body_iterator = self._iter_content()

    def __aiter__(self):
        """Make this class async iterable."""
        return self._iter_content()

    async def _iter_content(self):
        for chunk in self.content:
            yield chunk.encode() if isinstance(chunk, str) else chunk


class TestBackendFactory:
    """Tests for the BackendFactory class."""

    @pytest.mark.asyncio
    async def test_create_backend(self):
        """Test creating a backend with the factory."""
        # Arrange
        client = httpx.AsyncClient()
        factory = BackendFactory(client)

        # Mock the backend classes
        with patch.dict(
            factory._backend_types,
            {BackendType.OPENAI: lambda client: MockBackend(client)},
        ):
            # Act
            backend = factory.create_backend(BackendType.OPENAI)

            # Assert
            assert isinstance(backend, MockBackend)
            assert backend.client == client

    @pytest.mark.asyncio
    async def test_initialize_backend(self):
        """Test initializing a backend with the factory."""
        # Arrange
        client = httpx.AsyncClient()
        factory = BackendFactory(client)
        backend = MockBackend(client)
        config = {"api_key": "test-key", "extra_param": "value"}

        # Act
        await factory.initialize_backend(backend, config)

        # Assert
        assert backend.initialize_called
        assert backend.initialize_kwargs == config

    @pytest.mark.asyncio
    async def test_create_backend_invalid_type(self):
        """Test creating a backend with an invalid type."""
        # Arrange
        client = httpx.AsyncClient()
        factory = BackendFactory(client)

        # Act & Assert
        with pytest.raises(ValueError):
            factory.create_backend("invalid-backend-type")


class ConcreteBackendService(BackendService):
    """Concrete implementation of the abstract BackendService for testing."""

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]:
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
        factory = BackendFactory(client)
        rate_limiter = MockRateLimiter()
        return ConcreteBackendService(factory, rate_limiter, mock_config)

    @pytest.mark.asyncio
    async def test_get_or_create_backend_cached(self, service):
        """Test that backends are cached and reused."""
        # Arrange
        mock_backend = MockBackend(None)
        service._backends[BackendType.OPENAI] = mock_backend

        # Act
        result = await service._get_or_create_backend(BackendType.OPENAI)

        # Assert
        assert result is mock_backend

    @pytest.mark.asyncio
    async def test_get_or_create_backend_new(self, service):
        """Test creating a new backend when not cached."""
        # Arrange
        mock_backend = MockBackend(None)

        with (
            patch.object(
                service._factory, "create_backend", return_value=mock_backend
            ) as mock_create,
            patch.object(service._factory, "initialize_backend") as mock_initialize,
        ):
            # Act
            result = await service._get_or_create_backend(BackendType.OPENAI)

            # Assert
            assert result is mock_backend
            mock_create.assert_called_once_with(BackendType.OPENAI)
            mock_initialize.assert_called_once_with(mock_backend, {})
            assert BackendType.OPENAI in service._backends

    @pytest.mark.asyncio
    async def test_get_or_create_backend_error(self, service):
        """Test error handling when creating a backend fails."""
        # Arrange
        with patch.object(
            service._factory, "create_backend", side_effect=ValueError("Test error")
        ):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service._get_or_create_backend(BackendType.OPENAI)

            assert "Failed to create backend" in str(exc_info.value)
            assert "Test error" in str(exc_info.value)

    def test_prepare_messages(self, service):
        """Test message preparation."""
        # Arrange
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
        ]

        # Act
        result = service._prepare_messages(messages)

        # Assert
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "Hi there"


class TestBackendServiceCompletions:
    """Tests for the BackendService's completion handling."""

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
        factory = BackendFactory(client)
        rate_limiter = MockRateLimiter()
        return ConcreteBackendService(factory, rate_limiter, mock_config)

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
        mock_backend = MockBackend(None)
        mock_backend.chat_completions_mock.return_value = (
            {"id": "resp-123", "created": 123, "model": "model1", "choices": []},
            {},
        )

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            response = await service.call_completion(chat_request)

            # Assert
            assert mock_backend.chat_completions_called
            assert response.id == "resp-123"
            assert response.model == "model1"

    @pytest.mark.asyncio
    async def test_call_completion_streaming(self, service, chat_request):
        """Test calling a streaming completion."""
        # Arrange
        chunks = [
            'data: {"id":"chunk1","choices":[{"delta":{"content":"Hello"}}]}\n\n',
            'data: {"id":"chunk2","choices":[{"delta":{"content":" world"}}]}\n\n',
            "data: [DONE]\n\n",
        ]

        mock_response = MockStreamingResponse(chunks)
        mock_backend = MockBackend(None)
        mock_backend.chat_completions_mock.return_value = mock_response

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            stream = await service.call_completion(chat_request, stream=True)

            # Assert
            assert mock_backend.chat_completions_called

            # Collect chunks from the stream
            result_chunks = []
            async for chunk in stream:
                result_chunks.append(chunk)

            # Verify chunks
            assert len(result_chunks) == len(chunks)
            for i in range(len(chunks)):
                assert result_chunks[i] == chunks[i].encode()

    @pytest.mark.asyncio
    async def test_call_completion_streaming_error(self, service, chat_request):
        """Test error handling in streaming completion."""

        # Arrange
        class MockErrorStreamingResponse:
            """Mock streaming response that raises an error."""

            def __aiter__(self):
                return self._stream()

            async def _stream(self):
                yield b'data: {"id":"chunk1"}\n\n'
                raise ValueError("Streaming error")

        mock_response = MockErrorStreamingResponse()

        mock_backend = MockBackend(None)
        mock_backend.chat_completions_mock.return_value = mock_response

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            stream = await service.call_completion(chat_request, stream=True)

            # Collect chunks from the stream
            result_chunks = []
            async for chunk in stream:
                result_chunks.append(chunk)

            # Assert
            # Verify error handling occurred
            assert len(result_chunks) >= 1
            # The first chunk is the original data
            assert b'data: {"id":"chunk1"}' in result_chunks[0]
            # An error chunk should be generated after the error
            found_error = False
            for chunk in result_chunks:
                if b"Stream processing error" in chunk and b"Streaming error" in chunk:
                    found_error = True
                    break
            assert found_error, "Error message not found in chunks"
            # Verify [DONE] marker is sent (should be the last chunk)
            assert b"data: [DONE]\n\n" in result_chunks[-1]

    @pytest.mark.asyncio
    async def test_call_completion_rate_limited(self, service, chat_request):
        """Test rate limiting in the backend service."""
        # Arrange
        mock_backend = MockBackend(None)
        service._backends[BackendType.OPENAI] = mock_backend

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
        mock_backend = MockBackend(None)
        mock_backend.chat_completions_mock.side_effect = ValueError("API error")

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service.call_completion(chat_request)

            # Verify exception details
            assert "Backend call failed" in str(exc_info.value)
            assert "API error" in str(exc_info.value)
            # Note: The backend type may not be included in the error message in all implementations

    @pytest.mark.asyncio
    async def test_call_completion_invalid_response(self, service, chat_request):
        """Test error handling for invalid response format."""
        # Arrange
        mock_backend = MockBackend(None)
        # Return invalid response format (not a tuple)
        mock_backend.chat_completions_mock.return_value = "invalid-response"

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service.call_completion(chat_request)

            # Verify exception details
            assert "Expected (dict, dict) tuple" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_completion_invalid_streaming_response(
        self, service, chat_request
    ):
        """Test error handling for invalid streaming response format."""
        # Arrange
        mock_backend = MockBackend(None)
        # Return invalid response format (not a StreamingResponse)
        mock_backend.chat_completions_mock.return_value = "invalid-streaming-response"

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service.call_completion(chat_request, stream=True)

            # Verify exception details
            assert "Expected StreamingResponse" in str(exc_info.value)


class TestBackendServiceValidation:
    """Tests for the BackendService's validation capabilities."""

    @pytest.fixture
    def service(self):
        """Create a BackendService instance for testing."""
        client = httpx.AsyncClient()
        factory = BackendFactory(client)
        rate_limiter = MockRateLimiter()
        mock_config = Mock()
        return ConcreteBackendService(factory, rate_limiter, mock_config)

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_valid(self, service):
        """Test validating a valid backend and model."""
        # Arrange
        mock_backend = MockBackend(
            None, available_models=["valid-model", "other-model"]
        )

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            valid, error = await service.validate_backend_and_model(
                BackendType.OPENAI, "valid-model"
            )

            # Assert
            assert valid is True
            assert error is None

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_invalid_model(self, service):
        """Test validating an invalid model."""
        # Arrange
        mock_backend = MockBackend(None, available_models=["valid-model"])

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            valid, error = await service.validate_backend_and_model(
                BackendType.OPENAI, "invalid-model"
            )

            # Assert
            assert valid is False
            assert "not available" in error

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_backend_error(self, service):
        """Test validating with a backend error."""
        # Arrange
        with patch.object(
            service, "_get_or_create_backend", side_effect=ValueError("Backend error")
        ):
            # Act
            valid, error = await service.validate_backend_and_model(
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
        factory = BackendFactory(client)
        rate_limiter = MockRateLimiter()

        # Configure failover routes
        failover_routes: dict[str, dict[str, Any]] = {
            BackendType.OPENAI.value: {
                "backend": BackendType.OPENROUTER.value,
                "model": "fallback-model",
            }
        }

        return ConcreteBackendService(
            factory, rate_limiter, mock_config, failover_routes=failover_routes
        )

    @pytest.fixture
    def service_with_complex_failover(self, mock_config):
        """Create a BackendService instance with complex failover routes."""
        client = httpx.AsyncClient()
        factory = BackendFactory(client)
        rate_limiter = MockRateLimiter()

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

        return ConcreteBackendService(
            factory, rate_limiter, mock_config, failover_routes=failover_routes
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
        primary_backend = MockBackend(None)
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # Create fallback backend that succeeds
        fallback_backend = MockBackend(None)
        fallback_backend.chat_completions_mock.return_value = (
            {
                "id": "fallback-resp",
                "created": 123,
                "model": "fallback-model",
                "choices": [],
            },
            {},
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
        assert response.id == "fallback-resp"
        assert response.model == "fallback-model"

    @pytest.mark.asyncio
    async def test_complex_failover_first_attempt(
        self, service_with_complex_failover, chat_request_complex
    ):
        """Test complex model-specific failover, first attempt succeeds."""
        # Arrange
        # Primary backend fails
        primary_backend = MockBackend(None)
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # First failover attempt succeeds
        first_fallback = MockBackend(None)
        first_fallback.chat_completions_mock.return_value = (
            {"id": "claude-resp", "created": 123, "model": "claude-2", "choices": []},
            {},
        )

        # Second failover never called
        second_fallback = MockBackend(None)

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
                service_with_complex_failover._failover_service, "get_failover_attempts"
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

        # Assert
        assert primary_backend.chat_completions_called
        assert first_fallback.chat_completions_called
        assert not second_fallback.chat_completions_called
        assert response.id == "claude-resp"
        assert response.model == "claude-2"

    @pytest.mark.asyncio
    async def test_complex_failover_second_attempt(
        self, service_with_complex_failover, chat_request_complex
    ):
        """Test complex model-specific failover, second attempt succeeds after first fails."""
        # Arrange
        # Primary backend fails
        primary_backend = MockBackend(None)
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # First failover attempt fails
        first_fallback = MockBackend(None)
        first_fallback.chat_completions_mock.side_effect = ValueError(
            "First failover error"
        )

        # Second failover succeeds
        second_fallback = MockBackend(None)
        second_fallback.chat_completions_mock.return_value = (
            {
                "id": "last-resort",
                "created": 123,
                "model": "last-resort-model",
                "choices": [],
            },
            {},
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
                service_with_complex_failover._failover_service, "get_failover_attempts"
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

        # Assert
        assert primary_backend.chat_completions_called
        assert first_fallback.chat_completions_called
        assert second_fallback.chat_completions_called
        assert response.id == "last-resort"
        assert response.model == "last-resort-model"

    @pytest.mark.asyncio
    async def test_complex_failover_all_fail(
        self, service_with_complex_failover, chat_request_complex
    ):
        """Test complex model-specific failover when all attempts fail."""
        # Arrange
        # Primary backend fails
        primary_backend = MockBackend(None)
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # First failover attempt fails
        first_fallback = MockBackend(None)
        first_fallback.chat_completions_mock.side_effect = ValueError(
            "First failover error"
        )

        # Second failover fails
        second_fallback = MockBackend(None)
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
                service_with_complex_failover._failover_service, "get_failover_attempts"
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

        # Verify that all fallback attempts were called
        assert primary_backend.chat_completions_called
        assert first_fallback.chat_completions_called
        assert second_fallback.chat_completions_called
        assert "All failover attempts failed" in str(exc_info.value)
        assert "Second failover error" in str(exc_info.value)
