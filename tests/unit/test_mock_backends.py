"""
Tests for the mock backend factory and mock backends.
"""

import pytest
from unittest.mock import patch, MagicMock
import asyncio

from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.core.di.container import ServiceCollection, ServiceProvider
from src.core.interfaces.backend_service_interface import IBackendService
from src.connectors.base import LLMBackend
from tests.conftest import get_backend_instance
from tests.test_backend_factory import MockOpenAI, MockOpenRouter, MockGemini, MockAnthropicBackend


def test_mock_backends_initialization():
    """Test that mock backends are correctly initialized and registered."""
    # Create mock backends directly
    openai_backend = MockOpenAI()
    openrouter_backend = MockOpenRouter()
    gemini_backend = MockGemini()
    anthropic_backend = MockAnthropicBackend()
    
    # Check that they have the expected models
    assert "gpt-3.5-turbo" in openai_backend.available_models
    assert "gpt-4" in openai_backend.available_models
    assert "openrouter:gpt-4" in openrouter_backend.available_models
    assert "openrouter:claude-3-sonnet" in openrouter_backend.available_models
    assert "gemini:gemini-pro" in gemini_backend.available_models
    assert "claude-3-opus" in anthropic_backend.available_models


@pytest.mark.asyncio
async def test_mock_backend_chat_completions():
    """Test that mock backends correctly handle chat completions."""
    # Create a mock backend directly
    backend = MockOpenAI()
    
    # Create a chat request
    from src.core.domain.chat import ChatMessage, ChatRequest
    request = ChatRequest(
        model="gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Hello, world!")],
    )
    
    # Call the chat_completions method
    # We need to await the AsyncMock twice: once for the method call and once for the result
    response_coroutine = await backend.chat_completions(
        request_data=request,
        processed_messages=[{"role": "user", "content": "Hello, world!"}],
        effective_model="gpt-3.5-turbo",
    )
    response = await response_coroutine
    
    # Check the response
    assert response["id"] == "mock-openai-response"
    assert response["choices"][0]["message"]["content"] == "Mock openai response"


@pytest.mark.asyncio
async def test_configure_mock_response():
    """Test that we can configure the mock response."""
    # Create a mock backend directly
    backend = MockOpenAI()
    
    # Configure a custom response
    custom_response = {
        "id": "custom-response",
        "choices": [{"message": {"content": "Custom response"}}],
    }
    backend.configure_response(custom_response)
    
    # Create a chat request
    from src.core.domain.chat import ChatMessage, ChatRequest
    request = ChatRequest(
        model="gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Hello, world!")],
    )
    
    # Call the chat_completions method
    # We need to await the AsyncMock twice: once for the method call and once for the result
    response_coroutine = await backend.chat_completions(
        request_data=request,
        processed_messages=[{"role": "user", "content": "Hello, world!"}],
        effective_model="gpt-3.5-turbo",
    )
    response = await response_coroutine
    
    # Check the response
    assert response["id"] == "custom-response"
    assert response["choices"][0]["message"]["content"] == "Custom response"


@pytest.mark.asyncio
async def test_configure_streaming_response():
    """Test that we can configure a streaming response."""
    # Create a mock backend directly
    backend = MockOpenAI()
    
    # Configure a streaming response
    chunks = ["Hello", ", ", "world", "!"]
    backend.configure_streaming_response(chunks)
    
    # Create a chat request
    from src.core.domain.chat import ChatMessage, ChatRequest
    request = ChatRequest(
        model="gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Hello, world!")],
        stream=True,
    )
    
    # Call the chat_completions method
    # We need to await the AsyncMock twice: once for the method call and once for the result
    response_coroutine = await backend.chat_completions(
        request_data=request,
        processed_messages=[{"role": "user", "content": "Hello, world!"}],
        effective_model="gpt-3.5-turbo",
    )
    response = await response_coroutine
    
    # Check that the response is a StreamingResponse
    from fastapi.responses import StreamingResponse
    assert isinstance(response, StreamingResponse)
    
    # Collect the chunks
    chunks_received = []
    async for chunk in response.body_iterator:
        # The chunks might already be strings in our mock implementation
        if isinstance(chunk, bytes):
            chunks_received.append(chunk.decode("utf-8"))
        else:
            chunks_received.append(chunk)
    
    # Check the chunks
    assert len(chunks_received) == 4
    assert chunks_received[0] == "data: Hello\n\n"
    assert chunks_received[1] == "data: , \n\n"
    assert chunks_received[2] == "data: world\n\n"
    assert chunks_received[3] == "data: !\n\n"


@pytest.mark.asyncio
async def test_configure_error_response():
    """Test that we can configure an error response."""
    # Create a mock backend directly
    backend = MockOpenAI()
    
    # Configure an error response
    backend.configure_error(401, "Invalid API key")
    
    # Create a chat request
    from src.core.domain.chat import ChatMessage, ChatRequest
    request = ChatRequest(
        model="gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Hello, world!")],
    )
    
    # Call the chat_completions method and expect an exception
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        # We need to await the AsyncMock twice: once for the method call and once for the result
        response_coroutine = await backend.chat_completions(
            request_data=request,
            processed_messages=[{"role": "user", "content": "Hello, world!"}],
            effective_model="gpt-3.5-turbo",
        )
        await response_coroutine
    
    # Check the exception
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == {"error": "Invalid API key"}


@pytest.mark.skip(reason="Requires proper app setup with service provider")
def test_chat_completion_api_with_mock(test_app: FastAPI, test_client: TestClient):
    """Test that the chat completion API works with mock backends."""
    # Setup service provider
    services = ServiceCollection()
    
    # Create mock backend
    backend = MockOpenAI()
    backend.configure_response({
        "id": "test-response",
        "choices": [{"message": {"content": "This is a test response"}}],
    })
    
    # Create mock backend service
    backend_service = MagicMock(spec=IBackendService)
    backend_service._backends = {"openai": backend}
    backend_service.get_backend.return_value = backend
    
    # Register the service
    services.add_instance(IBackendService, backend_service)
    
    # Build the provider and attach to app
    provider = services.build_provider()
    test_app.state.service_provider = provider
    
    # Make a request to the API
    response = test_client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello, world!"}],
        },
    )
    
    # Check the response
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    assert len(data["choices"]) == 1
    assert data["choices"][0]["message"]["content"] == "This is a test response"


@pytest.mark.skip(reason="Requires proper app setup with service provider")
def test_mock_factory_fixture(test_app: FastAPI, test_client: TestClient, mock_backend_factory):
    """Test that the mock_backend_factory fixture works."""
    # Create and configure a backend
    backend = mock_backend_factory.create_backend("openai")
    backend.configure_response({
        "id": "fixture-test",
        "choices": [{"message": {"content": "Response from fixture"}}],
    })
    
    # Create mock backend service
    backend_service = MagicMock(spec=IBackendService)
    backend_service._backends = {"openai": backend}
    backend_service.get_backend.return_value = backend
    
    # Setup service provider
    services = ServiceCollection()
    services.add_instance(IBackendService, backend_service)
    
    # Build the provider and attach to app
    provider = services.build_provider()
    test_app.state.service_provider = provider
    
    # Make a request to the API
    response = test_client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello from fixture test!"}],
        },
    )
    
    # Check the response
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "fixture-test"
    assert data["choices"][0]["message"]["content"] == "Response from fixture"


@pytest.mark.skip(reason="This test requires real API keys and real backends")
def test_real_backend_fixture(test_client: TestClient):
    """Test that the use_real_backends fixture works.
    
    Note: This test will be skipped in CI because it requires real API keys.
    """
    # Check if we have real API keys
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("No real API keys available")
        
    # Make a request to the API
    response = test_client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Say 'This is a real response'"}],
        },
    )
    
    # Check the response
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    assert len(data["choices"]) == 1
    assert "This is a real response" in data["choices"][0]["message"]["content"]