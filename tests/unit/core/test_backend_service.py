"""
Tests for the BackendService implementation.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from src.connectors.base import LLMBackend
from src.constants import BackendType
from src.core.common.exceptions import RateLimitExceededError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService

from tests.unit.core.test_doubles import MockRateLimiter


class MockBackend(LLMBackend):
    """Mock implementation of LLMBackend for testing."""
    
    def __init__(self, client):
        self.client = client
        self.available_models = ["model1", "model2"]
        self.initialize_called = False
        self.chat_completions_called = False
        self.chat_completions_mock = AsyncMock()
    
    async def initialize(self, **kwargs):
        self.initialize_called = True
        self.initialize_kwargs = kwargs
    
    def get_available_models(self):
        return self.available_models
    
    async def chat_completions(self, request_data, processed_messages, effective_model, **kwargs):
        self.chat_completions_called = True
        self.chat_completions_args = {
            "request_data": request_data,
            "processed_messages": processed_messages,
            "effective_model": effective_model,
            "kwargs": kwargs
        }
        return await self.chat_completions_mock()


@pytest.mark.asyncio
async def test_backend_factory_create():
    """Test creating a backend with the factory."""
    # Arrange
    client = httpx.AsyncClient()
    factory = BackendFactory(client)
    
    # Mock the backend classes
    with patch.dict(factory._backend_types, {BackendType.OPENAI: lambda client: MockBackend(client)}):
        # Force the factory to use our mock
        factory._backend_types[BackendType.OPENAI] = lambda client: MockBackend(client)
        # Act
        backend = factory.create_backend(BackendType.OPENAI)
        
        # Assert
        assert isinstance(backend, MockBackend)
        assert backend.client == client


@pytest.mark.asyncio
async def test_backend_factory_initialize():
    """Test initializing a backend with the factory."""
    # Arrange
    client = httpx.AsyncClient()
    factory = BackendFactory(client)
    backend = MockBackend(client)
    config = {"api_key": "test-key"}
    
    # Act
    await factory.initialize_backend(backend, config)
    
    # Assert
    assert backend.initialize_called
    assert backend.initialize_kwargs == config


@pytest.mark.asyncio
async def test_backend_service_call_completion():
    """Test calling a completion with the service."""
    # Arrange
    client = httpx.AsyncClient()
    factory = BackendFactory(client)
    rate_limiter = MockRateLimiter()
    service = BackendService(factory, rate_limiter)
    
    # Create a request
    request = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Hello")
        ],
        model="model1",
        extra_body={"backend_type": BackendType.OPENAI}
    )
    
    # Mock the backend
    mock_backend = MockBackend(client)
    mock_backend.chat_completions_mock.return_value = (
        {"id": "resp-123", "created": 123, "model": "model1", "choices": []},
        {}
    )
    
    with patch.object(factory, "create_backend", return_value=mock_backend):
        # Act
        response = await service.call_completion(request)
        
        # Assert
        assert mock_backend.chat_completions_called
        assert response.id == "resp-123"
        assert response.model == "model1"


@pytest.mark.asyncio
async def test_backend_service_validate_model():
    """Test validating a model with the service."""
    # Arrange
    client = httpx.AsyncClient()
    factory = BackendFactory(client)
    rate_limiter = MockRateLimiter()
    service = BackendService(factory, rate_limiter)
    
    # Mock the backend
    mock_backend = MockBackend(client)
    mock_backend.available_models = ["valid-model"]
    
    with patch.object(factory, "create_backend", return_value=mock_backend):
        # Act - Valid model
        valid, error = await service.validate_backend_and_model(
            BackendType.OPENAI, "valid-model"
        )
        
        # Assert
        assert valid is True
        assert error is None
        
        # Act - Invalid model
        valid, error = await service.validate_backend_and_model(
            BackendType.OPENAI, "invalid-model"
        )
        
        # Assert
        assert valid is False
        assert "not available" in error


@pytest.mark.asyncio
async def test_backend_service_failover():
    """Test backend failover."""
    # Arrange
    client = httpx.AsyncClient()
    factory = BackendFactory(client)
    rate_limiter = MockRateLimiter()
    
    # Configure failover routes
    failover_routes = {
        BackendType.OPENAI: {
            "backend": BackendType.OPENROUTER,
            "model": "fallback-model"
        }
    }
    
    service = BackendService(
        factory, 
        rate_limiter, 
        failover_routes=failover_routes
    )
    
    # Create a request
    request = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Hello")
        ],
        model="model1",
        extra_body={"backend_type": BackendType.OPENAI}
    )
    
    # Mock the primary backend to fail
    primary_backend = MockBackend(client)
    primary_backend.chat_completions_mock.side_effect = Exception("API error")
    
    # Mock the fallback backend
    fallback_backend = MockBackend(client)
    fallback_backend.chat_completions_mock.return_value = (
        {"id": "fallback-resp", "created": 123, "model": "fallback-model", "choices": []},
        {}
    )
    
    def mock_create_backend(backend_type):
        if backend_type == BackendType.OPENAI:
            return primary_backend
        elif backend_type == BackendType.OPENROUTER:
            return fallback_backend
        raise ValueError(f"Unexpected backend type: {backend_type}")
    
    with patch.object(factory, "create_backend", side_effect=mock_create_backend):
        # Act
        response = await service.call_completion(request)
        
        # Assert
        assert primary_backend.chat_completions_called
        assert fallback_backend.chat_completions_called
        assert response.id == "fallback-resp"
        assert response.model == "fallback-model"


@pytest.mark.asyncio
async def test_backend_service_rate_limit():
    """Test rate limiting in the backend service."""
    # Arrange
    client = httpx.AsyncClient()
    factory = BackendFactory(client)
    rate_limiter = MockRateLimiter()
    service = BackendService(factory, rate_limiter)
    
    # Create a mock backend and add it to the service's backend cache
    mock_backend = MockBackend(client)
    service._backends[BackendType.OPENAI] = mock_backend

    # Create a request
    request = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Hello")
        ],
        model="model1",
        extra_body={"backend_type": BackendType.OPENAI}
    )

    # Configure rate limiter to report limit exceeded
    from src.core.interfaces.rate_limiter import RateLimitInfo
    rate_limiter.limits[f"backend:{BackendType.OPENAI}"] = RateLimitInfo(
        is_limited=True,
        remaining=0,
        reset_at=123,
        limit=10,
        time_window=60
    )

    # Act & Assert
    with pytest.raises(RateLimitExceededError) as exc:
        await service.call_completion(request)
        
            # Verify the exception details
        assert exc.value.details.get('reset_at') == 123
    
    assert "Rate limit exceeded" in str(exc.value)
