"""
Simplified integration test using the official Google Gemini API client library.
"""
import pytest

pytestmark = pytest.mark.integration
from unittest.mock import patch, MagicMock, AsyncMock, Mock
from fastapi.testclient import TestClient

# Official Google Gemini client
try:
    import google.genai as genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from src.main import build_app


@pytest.fixture
def test_app():
    """Create test app with disabled auth."""
    config = {
        "disable_auth": True,
        "interactive_mode": False,
        "command_prefix": "/",
        "disable_interactive_commands": True,
        "proxy_timeout": 30.0,
        "openrouter_api_base_url": "https://openrouter.ai/api/v1",
        "gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "openrouter_api_keys": {"test": "test-openrouter-key"},
        "gemini_api_keys": {"test": "test-gemini-key"},
    }
    return build_app(config)


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


def test_gemini_client_creation():
    """Test that we can create a Gemini client with custom URL."""
    # Create client with custom base URL (would point to our proxy in real scenario)
    client = genai.Client(
        api_key="test-api-key",
        http_options=genai_types.HttpOptions(
            base_url="http://localhost:8000"  # Would be our proxy URL
        )
    )
    
    assert client is not None
    # Check that the client was created successfully
    assert hasattr(client, 'models')


def test_gemini_models_endpoint_format(client):
    """Test that our models endpoint returns Gemini-compatible format."""
    # Mock the functional backends and backend models
    client.app.state.functional_backends = {"openrouter", "gemini", "gemini-cli-direct"}
    
    # Create mock backends
    mock_or = MagicMock()
    mock_or.get_available_models.return_value = ["gpt-4", "gpt-3.5-turbo"]
    client.app.state.openrouter_backend = mock_or
    
    mock_gemini = MagicMock()
    mock_gemini.get_available_models.return_value = ["gemini-pro", "gemini-pro-vision"]
    client.app.state.gemini_backend = mock_gemini
    
    mock_cli = MagicMock()
    mock_cli.get_available_models.return_value = ["gemini-1.5-pro"]
    client.app.state.gemini_cli_direct_backend = mock_cli
    
    # Test Gemini models endpoint
    response = client.get("/v1beta/models")
    assert response.status_code == 200
    
    data = response.json()
    assert "models" in data
    assert len(data["models"]) > 0
    
    # Check first model has Gemini format
    model = data["models"][0]
    assert "name" in model
    assert "display_name" in model
    assert "supported_generation_methods" in model
    assert "generateContent" in model["supported_generation_methods"]
    assert "streamGenerateContent" in model["supported_generation_methods"]


def test_gemini_generate_content_endpoint_format(configured_app):
    """Test that generate content endpoint accepts and returns Gemini format."""
    # Mock the backend to return a response
    mock_backend = Mock()
    mock_backend.chat_completions = AsyncMock(return_value={
        "id": "test-id",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! This is a test response."
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 15,
            "total_tokens": 25
        }
    })

    # Use TestClient with context manager to trigger lifespan events
    with TestClient(configured_app) as client:
        # Mock the openrouter backend in the app state
        client.app.state.openrouter_backend = mock_backend
        # Set available_models to avoid coroutine issues in welcome banner
        mock_backend.available_models = ["test-model"]
        # Mock get_available_models to return a list, not a coroutine
        mock_backend.get_available_models.return_value = ["test-model"]

        # Send Gemini format request
        gemini_request = {
            "contents": [
                {
                    "parts": [
                        {"text": "Hello, how are you?"}
                    ],
                    "role": "user"
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 100
            }
        }

        response = client.post(
            "/v1beta/models/test-model:generateContent",
            json=gemini_request,
            headers={"x-goog-api-key": "test-proxy-key"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check Gemini response format
        assert "candidates" in data
        assert len(data["candidates"]) == 1
        
        candidate = data["candidates"][0]
        assert "content" in candidate
        assert "finishReason" in candidate
        assert candidate["finishReason"] == "STOP"
        
        content = candidate["content"]
        assert "parts" in content
        assert "role" in content
        assert content["role"] == "model"
        assert len(content["parts"]) == 1
        # Check that the response contains our expected text (may include banner)
        response_text = content["parts"][0]["text"]
        assert "Hello! This is a test response." in response_text
        
        # Check usage metadata
        assert "usageMetadata" in data
        usage = data["usageMetadata"]
        assert usage["promptTokenCount"] == 10
        assert usage["candidatesTokenCount"] == 15
        assert usage["totalTokenCount"] == 25


def test_gemini_request_conversion_to_openai(configured_app):
    """Test that Gemini requests are properly converted to OpenAI format."""
    # Mock the backend to return a response
    mock_backend = Mock()
    mock_backend.chat_completions = AsyncMock(return_value={
        "id": "test-id",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Response"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 5,
            "total_tokens": 10
        }
    })

    # Use TestClient with context manager to trigger lifespan events
    with TestClient(configured_app) as client:
        # Mock the openrouter backend in the app state
        client.app.state.openrouter_backend = mock_backend
        # Set available_models to avoid coroutine issues in welcome banner
        mock_backend.available_models = ["test-model"]
        # Mock get_available_models to return a list, not a coroutine
        mock_backend.get_available_models.return_value = ["test-model"]
        
        # Send complex Gemini request
        gemini_request = {
            "contents": [
                {
                    "parts": [{"text": "What is AI?"}],
                    "role": "user"
                },
                {
                    "parts": [{"text": "AI is artificial intelligence..."}],
                    "role": "model"
                },
                {
                    "parts": [{"text": "Can you elaborate?"}],
                    "role": "user"
                }
            ],
            "systemInstruction": {
                "parts": [{"text": "You are a helpful AI assistant."}]
            },
            "generationConfig": {
                "temperature": 0.8,
                "maxOutputTokens": 200,
                "topP": 0.9,
                "topK": 40
            }
        }
        
        response = client.post(
            "/v1beta/models/test-model:generateContent",
            json=gemini_request,
            headers={"x-goog-api-key": "test-proxy-key"}
        )
        
        assert response.status_code == 200
        
        # Verify the backend was called
        mock_backend.chat_completions.assert_called_once()
        
        # Get the converted OpenAI request from the call
        call_args = mock_backend.chat_completions.call_args
        
        # The request should be the first argument (either positional or keyword)
        if call_args.args:
            openai_request = call_args.args[0]
        else:
            openai_request = call_args.kwargs.get('request_data') or call_args.kwargs.get('request')
        
        # Check system instruction conversion
        assert len(openai_request.messages) == 4  # system + 3 conversation messages
        assert openai_request.messages[0].role == "system"
        assert openai_request.messages[0].content == "You are a helpful AI assistant."
        
        # Check conversation conversion
        assert openai_request.messages[1].role == "user"
        assert openai_request.messages[1].content == "What is AI?"
        assert openai_request.messages[2].role == "assistant"
        assert openai_request.messages[2].content == "AI is artificial intelligence..."
        assert openai_request.messages[3].role == "user"
        assert openai_request.messages[3].content == "Can you elaborate?"
        
        # Check generation config conversion
        assert openai_request.temperature == 0.8
        assert openai_request.max_tokens == 200
        assert openai_request.top_p == 0.9


@pytest.mark.skipif(not GENAI_AVAILABLE, reason="google.genai not installed")
def test_backend_routing_through_gemini_format(configured_app):
    """Test that different backends can be accessed through Gemini format."""
    # Mock responses for different backends
    mock_openrouter = Mock()
    mock_openrouter.chat_completions = AsyncMock(return_value={
        "id": "test-id",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "test-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OpenRouter response"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}
    })
    mock_openrouter.available_models = ["gpt-4"]
    mock_openrouter.get_available_models.return_value = ["gpt-4"]

    mock_gemini = Mock()
    mock_gemini.chat_completions = AsyncMock(return_value={
        "id": "test-id-2",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gemini-pro",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Gemini response"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}
    })
    mock_gemini.available_models = ["gemini-pro"]
    mock_gemini.get_available_models.return_value = ["gemini-pro"]

    mock_gemini_cli = Mock()
    mock_gemini_cli.chat_completions = AsyncMock(return_value={
        "id": "test-id-3",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gemini-1.5-pro",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Gemini CLI response"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}
    })
    mock_gemini_cli.available_models = ["gemini-1.5-pro"]
    mock_gemini_cli.get_available_models.return_value = ["gemini-1.5-pro"]

    # Use TestClient with context manager to trigger lifespan events
    with TestClient(configured_app) as client:
        # Mock all backends in the app state
        client.app.state.openrouter_backend = mock_openrouter
        client.app.state.gemini_backend = mock_gemini
        client.app.state.gemini_cli_direct_backend = mock_gemini_cli
        
        gemini_request = {
            "contents": [{"parts": [{"text": "Test message"}], "role": "user"}]
        }
        
        # Test different backend models through Gemini API
        test_cases = [
            ("openrouter:gpt-4", "OpenRouter response"),
            ("gemini:gemini-pro", "Gemini response"),
            ("gemini-cli-direct:gemini-1.5-pro", "Gemini CLI response")
        ]
        
        for model, expected_content in test_cases:
            response = client.post(
                f"/v1beta/models/{model}:generateContent",
                json=gemini_request,
                headers={"x-goog-api-key": "test-proxy-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "candidates" in data
            # Check that the response contains our expected text (may include banner)
            response_text = data["candidates"][0]["content"]["parts"][0]["text"]
            assert expected_content in response_text
        
        # Verify all backends were called
        mock_openrouter.chat_completions.assert_called_once()
        mock_gemini.chat_completions.assert_called_once()
        mock_gemini_cli.chat_completions.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 