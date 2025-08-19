"""
Integration tests for the new architecture.

These tests validate that the new architecture works end-to-end.
"""

import json
import logging
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig, AuthConfig
from src.core.di.services import get_service_collection, register_core_services
from src.core.interfaces.app_settings_interface import IAppSettings
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_resolver_interface import ISessionResolver

logger = logging.getLogger(__name__)


@pytest.fixture
def app_config() -> AppConfig:
    """Create an AppConfig for testing."""
    config = AppConfig(
        host="localhost",
        port=8000,
        debug=True,
        config_file="test_config.json",
        default_backend="mock",
        default_model="mock-model",
        command_prefix="!/",
    )
    
    # Disable authentication for tests
    config.auth = AuthConfig(
        disable_auth=True,
        api_keys=[],
        redact_api_keys_in_prompts=False
    )
    
    return config


@pytest.fixture
def app(app_config: AppConfig) -> FastAPI:
    """Create a FastAPI app for testing."""
    # Create a new service collection
    services = get_service_collection()
    
    # Register core services
    register_core_services(services, app_config)
    
    # Build the service provider
    service_provider = services.build_service_provider()
    
    # Create the application builder
    builder = ApplicationBuilder()
    
    # Build the app
    app = builder.build(app_config, service_provider)
    
    return app


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Create a test client."""
    with TestClient(app) as client:
        yield client


def test_app_has_service_provider(app: FastAPI) -> None:
    """Test that the app has a service provider."""
    assert hasattr(app.state, "service_provider")
    assert app.state.service_provider is not None


def test_service_provider_has_required_services(app: FastAPI) -> None:
    """Test that the service provider has all required services."""
    service_provider = app.state.service_provider
    
    # Check that the service provider has all required services
    assert service_provider.get_service(IRequestProcessor) is not None
    assert service_provider.get_service(ICommandProcessor) is not None
    assert service_provider.get_service(IBackendProcessor) is not None
    assert service_provider.get_service(IResponseProcessor) is not None
    assert service_provider.get_service(ISessionResolver) is not None
    assert service_provider.get_service(IAppSettings) is not None


def test_chat_completion_endpoint(client: TestClient) -> None:
    """Test that the chat completion endpoint works."""
    # Create a chat request
    request_data = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "Hello, world!"}
        ],
        "stream": False,
    }
    
    # Mock the backend service to avoid actual API calls
    from unittest.mock import patch
    
    # Patch the backend service to return a mock response
    with patch("src.core.services.backend_service.BackendService.call_completion") as mock_call_completion:
        from src.core.domain.responses import ResponseEnvelope
        
        # Create a mock response
        mock_response = ResponseEnvelope(
            content={
                "id": "chatcmpl-mock-123",
                "object": "chat.completion",
                "created": 1677858242,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello! How can I help you today?"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20
                }
            },
            headers={"content-type": "application/json"},
            status_code=200
        )
        
        # Set the return value of the mock
        mock_call_completion.return_value = mock_response
        
        # Send the request
        response = client.post("/v1/chat/completions", json=request_data)
        
        # Check the response
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        
        # Parse the response
        response_data = response.json()
        
        # Check the response data
        assert response_data["model"] == "mock-model"
        assert len(response_data["choices"]) > 0
        assert response_data["choices"][0]["message"]["role"] == "assistant"
        assert response_data["choices"][0]["message"]["content"] is not None


def test_command_processing(client: TestClient) -> None:
    """Test that command processing works."""
    # Create a chat request with a command
    request_data = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "!/help"}
        ],
        "stream": False,
    }
    
    # Mock both command processor and backend service
    from unittest.mock import patch
    
    # First patch backend service to avoid API calls
    with patch("src.core.services.backend_service.BackendService.call_completion") as mock_backend_call:
        from src.core.domain.responses import ResponseEnvelope
        
        # Create a mock backend response
        mock_backend_response = ResponseEnvelope(
            content={
                "id": "backend-mock-123",
                "object": "chat.completion",
                "created": 1677858242,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "This is a backend response"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20
                }
            },
            headers={"content-type": "application/json"},
            status_code=200
        )
        
        # Set the return value of the backend mock
        mock_backend_call.return_value = mock_backend_response
        
        # Then patch command processor to return a help message
        with patch("src.core.services.command_processor.CommandProcessor.process_commands") as mock_process_commands:
            from src.core.domain.processed_result import ProcessedResult
            
            # Create a mock command response with response property
            mock_command_response = {
                "id": "command-mock-123",
                "object": "chat.completion",
                "created": 1677858242,
                "model": "command",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Available commands:\n- help: Show this help message\n- model: Set the model to use"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 20,
                    "total_tokens": 25
                }
            }
            
            mock_result = ProcessedResult(
                modified_messages=[],
                command_executed=True,
                command_results=[mock_command_response]
            )
            
            # We can't modify the ProcessedResult object directly
            # Instead, patch the request processor to use our mock response directly
            with patch("src.core.services.request_processor_service.RequestProcessor._process_command_result") as mock_process_result:
                mock_process_result.return_value = mock_command_response
            
            # Set the return value of the command mock
            mock_process_commands.return_value = mock_result
        
            # Send the request
            response = client.post("/v1/chat/completions", json=request_data)
            
            # Check the response
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/json"
            
            # Parse the response
            response_data = response.json()
            
            # Check the response data - should contain help information
            assert "help" in response_data["choices"][0]["message"]["content"].lower()


def test_streaming_response(client: TestClient) -> None:
    """Test that streaming responses work."""
    # Create a chat request
    request_data = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "Hello, world!"}
        ],
        "stream": True,
    }
    
    # Send the request
    response = client.post("/v1/chat/completions", json=request_data, stream=True)
    
    # Check the response
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream"
    
    # Read the streaming response
    chunks = []
    for chunk in response.iter_lines():
        if chunk:
            # Remove the "data: " prefix
            if chunk.startswith(b"data: "):
                chunk = chunk[6:]
                
            # Skip empty chunks
            if chunk and chunk != b"[DONE]":
                try:
                    # Parse the chunk as JSON
                    chunk_data = json.loads(chunk)
                    chunks.append(chunk_data)
                except json.JSONDecodeError:
                    # Skip invalid JSON
                    pass
    
    # Check that we got at least one chunk
    assert len(chunks) > 0
    
    # Check that the chunks have the expected format
    for chunk in chunks:
        assert "id" in chunk
        assert "choices" in chunk
        if "delta" in chunk["choices"][0]:
            assert "role" in chunk["choices"][0]["delta"] or "content" in chunk["choices"][0]["delta"]


def test_anthropic_endpoint(client: TestClient) -> None:
    """Test that the Anthropic endpoint works."""
    # Create an Anthropic request
    request_data = {
        "model": "claude-3-opus-20240229",
        "messages": [
            {"role": "user", "content": "Hello, world!"}
        ],
        "stream": False,
    }
    
    # Send the request
    response = client.post("/anthropic/v1/messages", json=request_data)
    
    # Check the response
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    
    # Parse the response
    response_data = response.json()
    
    # Check the response data
    assert "id" in response_data
    assert "content" in response_data
    assert response_data["content"][0]["type"] == "text"
    assert response_data["content"][0]["text"] is not None
