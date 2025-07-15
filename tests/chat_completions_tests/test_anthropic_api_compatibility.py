import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from src.main import build_app
from src.models import ChatCompletionResponse, ChatCompletionChoice, ChatCompletionChoiceMessage, CompletionUsage

@pytest.fixture
def test_app():
    """Create a test FastAPI app instance."""
    with patch("src.main._load_config") as mock_load_config:
        mock_load_config.return_value = {
            "disable_auth": False,
            "disable_accounting": True,
            "proxy_timeout": 10,
            "interactive_mode": False,
            "command_prefix": "!/",
            "openrouter_api_keys": {"test_key": "test_value"},
            "openrouter_api_base_url": "https://openrouter.ai/api/v1",
            "gemini_api_keys": {"test_gemini_key": "test_gemini_value"},
            "gemini_api_base_url": "https://generativelanguage.googleapis.com",
            "backend": "openrouter",
            "client_api_key": "test_client_key",
        }
        app = build_app()
        app.state.client_api_key = "test_client_key"  # Explicitly set the key for the test
        with TestClient(app) as client:
            # Mock the backend initialization to avoid real API calls
            app.state.openrouter_backend.get_available_models = MagicMock(return_value=["model1", "model2"])
            app.state.gemini_backend.get_available_models = MagicMock(return_value=["gemini/gemini-pro"])
            app.state.gemini_cli_direct_backend.get_available_models = MagicMock(return_value=["gemini-cli-model"])
            app.state.gemini_cli_batch_backend.get_available_models = MagicMock(return_value=["gemini-cli-batch-model"])
            app.state.functional_backends = {"openrouter", "gemini", "gemini-cli-direct", "gemini-cli-batch"}
            yield client

def test_anthropic_messages_non_streaming(test_app):
    """Test the Anthropic API compatibility endpoint for non-streaming requests."""
    
    anthropic_request = {
        "model": "some-model",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Hello, world!"}]
    }

    mock_openai_response = ChatCompletionResponse(
        id="chatcmpl-123",
        object="chat.completion",
        created=1677652288,
        model="openrouter:some-model",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant",
                    content="This is a test response."
                ),
                finish_reason="stop"
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30
        )
    )

    # Patch the backend call instead of the internal chat_completions function
    with patch("src.connectors.openrouter.OpenRouterBackend.chat_completions", new_callable=AsyncMock) as mock_backend_chat_completions:
        # The backend returns a tuple of (response_dict, headers_dict)
        mock_backend_chat_completions.return_value = (mock_openai_response.model_dump(exclude_none=True), {})

        response = test_app.post(
            "/v1/messages",
            json=anthropic_request,
            headers={"x-api-key": "test_client_key"}
        )

        assert response.status_code == 200
        response_data = response.json()
        
        assert response_data["content"][0]["text"] == "This is a test response."
        assert response_data["stop_reason"] == "stop"
        assert response_data["usage"]["input_tokens"] == 10
        assert response_data["usage"]["output_tokens"] == 20

        mock_backend_chat_completions.assert_called_once()
        # Check the call arguments for the mocked function
        kwargs = mock_backend_chat_completions.call_args.kwargs
        openai_request = kwargs['request_data']
        
        assert openai_request.model == "some-model"
        assert len(openai_request.messages) == 1
        assert openai_request.messages[0].role == "user"
        assert openai_request.messages[0].content == "Hello, world!"
        assert not openai_request.stream
