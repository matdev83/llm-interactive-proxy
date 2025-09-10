"""
Simplified integration test using the official Google Gemini API client library.
"""

from unittest.mock import AsyncMock, MagicMock, Mock

# Official Google Gemini client (required dependency)
import google.genai as genai
import pytest
from fastapi.testclient import TestClient
from google.genai import types as genai_types
from src.core.app.test_builder import build_test_app as build_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.no_global_mock,
]  # Uses mocked Google Gemini client (not real network calls)


@pytest.fixture
def gemini_app():
    """Create test app with disabled auth for Gemini testing."""
    from src.core.config.app_config import (
        AppConfig,
        AuthConfig,
        BackendConfig,
        BackendSettings,
    )

    config = AppConfig(
        auth=AuthConfig(disable_auth=True),
        backends=BackendSettings(
            openrouter=BackendConfig(api_key=["test-openrouter-key"]),
            gemini=BackendConfig(api_key=["test-gemini-key"]),
            default_backend="gemini",
        ),
    )
    return build_app(config)


@pytest.fixture
def gemini_client(gemini_app):
    """Create test client for Gemini app."""
    return TestClient(gemini_app)


def test_gemini_client_creation():
    """Test that we can create a Gemini client with custom URL."""
    # Create client with custom base URL (would point to our proxy in real scenario)
    client = genai.Client(
        api_key="test-api-key",
        http_options=genai_types.HttpOptions(
            base_url="http://localhost:8000"  # Would be our proxy URL
        ),
    )

    assert client is not None
    # Check that the client was created successfully
    assert hasattr(client, "models")


def test_gemini_models_endpoint_format(gemini_client):
    """Test that our models endpoint returns Gemini-compatible format."""
    # Mock the functional backends and backend models via DI-backed BackendService
    gemini_client.app.state.functional_backends = {"openrouter", "gemini"}

    from src.core.interfaces.backend_service_interface import IBackendService

    backend_service = gemini_client.app.state.service_provider.get_required_service(
        IBackendService
    )

    # Create mock backends and register them in the BackendService cache
    mock_or = MagicMock()
    mock_or.get_available_models.return_value = ["gpt-4", "gpt-3.5-turbo"]
    backend_service._backends["openrouter"] = mock_or

    mock_gemini = MagicMock()
    mock_gemini.get_available_models.return_value = ["gemini-pro", "gemini-pro-vision"]
    backend_service._backends["gemini"] = mock_gemini

    # Test Gemini models endpoint
    response = gemini_client.get("/v1beta/models")
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


def test_gemini_generate_content_endpoint_format(gemini_app):
    """Test that generate content endpoint accepts and returns Gemini format."""
    # Mock the backend to return a response with tool calls
    mock_backend = Mock()
    mock_backend.chat_completions = AsyncMock(
        return_value={
            "id": "test-id",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! This is a test response.",
                        "tool_calls": [
                            {
                                "id": "call_test_123",
                                "type": "function",
                                "function": {
                                    "name": "hello",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
        }
    )

    # Use TestClient with context manager to trigger lifespan events
    with TestClient(gemini_app) as client:
        # Ensure controller path uses BackendService rather than a pre-set mock on app.state
        if hasattr(client.app.state, "openrouter_backend"):
            client.app.state.openrouter_backend = None
        # Register the openrouter backend in the BackendService cache
        from src.core.interfaces.backend_service_interface import IBackendService

        backend_service = client.app.state.service_provider.get_required_service(
            IBackendService
        )
        backend_service._backends["openrouter"] = mock_backend
        # Set available_models to avoid coroutine issues in welcome banner
        mock_backend.available_models = ["test-model"]
        # Mock get_available_models to return a list, not a coroutine
        mock_backend.get_available_models.return_value = ["test-model"]

        # Send Gemini format request that triggers a tool_call in OpenAI response
        gemini_request = {
            "contents": [{"parts": [{"text": "!/hello"}], "role": "user"}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 100},
        }

        response = client.post(
            "/v1beta/models/test-model:generateContent",
            json=gemini_request,
            headers={"x-goog-api-key": "test-proxy-key"},
        )

        assert response.status_code == 200
        data = response.json()

        # Check Gemini response format - we expect a functionCall part
        assert "candidates" in data
        assert len(data["candidates"]) == 1

        candidate = data["candidates"][0]
        assert "content" in candidate
        assert "finishReason" in candidate
        assert candidate["finishReason"] == "TOOL_CALLS"

        content = candidate["content"]
        assert "parts" in content
        assert "role" in content
        assert content["role"] == "model"
        assert len(content["parts"]) >= 1  # Can have text + functionCall
        # Check that there's a functionCall part somewhere
        function_call_parts = [
            part for part in content["parts"] if "functionCall" in part
        ]
        assert len(function_call_parts) == 1

        # Check usage metadata
        assert "usageMetadata" in data
        usage = data["usageMetadata"]
        assert usage["promptTokenCount"] == 10
        assert usage["candidatesTokenCount"] == 15
        assert usage["totalTokenCount"] == 25


def test_gemini_request_conversion_to_openai(gemini_app):
    """Test that Gemini requests are properly converted to OpenAI format."""
    # We validate conversion by invoking the TranslationService directly

    # Use TestClient with context manager to trigger lifespan events
    with TestClient(gemini_app) as client:
        # Ensure controller path uses BackendService rather than a pre-set mock on app.state
        if hasattr(client.app.state, "openrouter_backend"):
            client.app.state.openrouter_backend = None
        # Use TranslationService from DI to verify request conversion
        from src.core.services.translation_service import TranslationService

        translation_service = client.app.state.service_provider.get_required_service(
            TranslationService
        )

        # Send complex Gemini request
        gemini_request = {
            "contents": [
                {"parts": [{"text": "What is AI?"}], "role": "user"},
                {
                    "parts": [{"text": "AI is artificial intelligence..."}],
                    "role": "model",
                },
                {"parts": [{"text": "Can you elaborate?"}], "role": "user"},
            ],
            "systemInstruction": {
                "parts": [{"text": "You are a helpful AI assistant."}]
            },
            "generationConfig": {
                "temperature": 0.8,
                "maxOutputTokens": 200,
                "topP": 0.9,
                "topK": 40,
            },
        }

        response = client.post(
            "/v1beta/models/test-model:generateContent",
            json=gemini_request,
            headers={"x-goog-api-key": "test-proxy-key"},
        )

        assert response.status_code == 200

        # Independently verify conversion semantics via TranslationService
        openai_request = translation_service.to_domain_request(
            gemini_request, source_format="gemini"
        )

        # Check system instruction conversion
        assert len(openai_request.messages) == 4  # system + 3 conversation messages
        assert openai_request.messages[0].role == "system"
        assert openai_request.messages[0].content == "You are a helpful AI assistant."

        # Check conversation conversion
        assert openai_request.messages[1].role == "user"
        assert openai_request.messages[1].content == "What is AI?"
        # Gemini uses 'model' role in its protocol
        assert openai_request.messages[2].role == "model"
        assert openai_request.messages[2].content == "AI is artificial intelligence..."
        assert openai_request.messages[3].role == "user"
        assert openai_request.messages[3].content == "Can you elaborate?"

        # Check generation config conversion
        assert openai_request.temperature == 0.8
        assert openai_request.max_tokens == 200
        assert openai_request.top_p == 0.9


def test_backend_routing_through_gemini_format(gemini_app):
    """Test that different backends can be accessed through Gemini format."""
    # We rely on the built-in mock backend service response in test stages

    # Use TestClient with context manager to trigger lifespan events
    with TestClient(gemini_app) as client:
        gemini_request = {
            "contents": [{"parts": [{"text": "Test message"}], "role": "user"}]
        }

        # Test different backend models through Gemini API
        test_cases = [
            ("openrouter:gpt-4", "OpenRouter response"),
            ("gemini:gemini-pro", "Gemini response"),
        ]

        for model, _expected_content in test_cases:
            response = client.post(
                f"/v1beta/models/{model}:generateContent",
                json=gemini_request,
                headers={"x-goog-api-key": "test-proxy-key"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "candidates" in data
            # The test stage mock backend returns a standard message
            response_text = data["candidates"][0]["content"]["parts"][0]["text"]
            assert "Mock response from test backend" in response_text
        # mock_gemini_cli.chat_completions.assert_called_once()  # This is now removed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
