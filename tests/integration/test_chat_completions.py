import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from httpx import Response # For constructing mock client responses if needed by TestClient directly
from starlette.responses import StreamingResponse # If we need to mock this directly

# Import the FastAPI app instance from your main application file
# Adjust the import path according to your project structure.
# Assuming your FastAPI app instance is named 'app' in 'src/main.py'
from src.main import app, get_openrouter_headers # Import app and any direct dependencies for mocking
from src.models import ChatMessage, ChatCompletionRequest # For constructing request payloads
from src.proxy_logic import proxy_state # To check state if necessary

# Fixture to provide a TestClient instance
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

# Fixture to automatically reset proxy_state before each test
@pytest.fixture(autouse=True)
def reset_global_proxy_state():
    proxy_state.unset_override_model() # Assuming this resets it to None

# --- Test Cases ---

def test_basic_request_proxying_non_streaming(client: TestClient):
    mock_backend_response = {
        "id": "comp-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-3.5-turbo",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello from mock backend!"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21}
    }

    # Patch the 'chat_completions' method of the OpenRouterBackend instance
    # that is stored in app.state.openrouter_backend
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.json() == mock_backend_response

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1] # Get kwargs
    assert call_args['request_data'].model == "gpt-3.5-turbo"
    assert call_args['request_data'].stream is False
    assert call_args['effective_model'] == "gpt-3.5-turbo"
    assert len(call_args['processed_messages']) == 1
    assert call_args['processed_messages'][0].content == "Hello"
    assert call_args['openrouter_headers_provider'] is not None # Check if provider was passed


@pytest.mark.asyncio # For using async capabilities if needed, though TestClient is sync
async def test_basic_request_proxying_streaming(client: TestClient):
    # Simulate a streaming response from the backend mock
    async def mock_stream_gen():
        yield b"data: chunk1\n\n"
        yield b"data: chunk2\n\n"
        yield b"data: [DONE]\n\n"

    # The backend's chat_completions method should return a StreamingResponse
    mock_streaming_response = StreamingResponse(mock_stream_gen(), media_type="text/event-stream")

    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_streaming_response

        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Stream test"}],
            "stream": True
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream"

    # Consume the stream from the TestClient response
    stream_content = b""
    for chunk in response.iter_bytes(): # Use iter_bytes for TestClient
        stream_content += chunk

    assert stream_content == b"data: chunk1\n\ndata: chunk2\n\ndata: [DONE]\n\n"

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['request_data'].stream is True


def test_set_model_command_integration(client: TestClient):
    mock_backend_response = {"choices": [{"message": {"content": "Model set and called."}}]} # Simplified

    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        payload = {
            "model": "original-model",
            "messages": [{"role": "user", "content": "Use this: !/set(model=override-model) Hello"}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert proxy_state.override_model == "override-model" # Check global state

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['request_data'].model == "original-model" # Original request model
    assert call_args['effective_model'] == "override-model"   # Model passed to backend
    assert call_args['processed_messages'][0].content == "Use this: Hello" # Command stripped


def test_unset_model_command_integration(client: TestClient):
    # First, set an override model directly or via a previous call (state persists in TestClient context if not careful)
    proxy_state.set_override_model("initial-override")

    mock_backend_response = {"choices": [{"message": {"content": "Model unset and called."}}]}

    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        payload = {
            "model": "another-model",
            "messages": [{"role": "user", "content": "Please !/unset(model) use default."}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert proxy_state.override_model is None # Override should be cleared

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['effective_model'] == "another-model" # Effective model is the original request model
    assert call_args['processed_messages'][0].content == "Please use default."


def test_command_only_request_direct_response(client: TestClient):
    # This type of request should not even call the backend connector
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/set(model=command-only-model)"}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"
    assert "Proxy command processed" in response_json["choices"][0]["message"]["content"]
    assert response_json["model"] == "command-only-model" # Model in response reflects override

    mock_method.assert_not_called() # Backend should not have been called
    assert proxy_state.override_model == "command-only-model" # State should be updated


def test_empty_messages_after_processing_no_commands_bad_request(client: TestClient):
    # This test ensures that if messages become empty *without* any commands being processed,
    # it's treated as a bad request by the main endpoint logic before calling the backend.

    # To achieve this, we need to mock process_commands_in_messages to return empty messages
    # and commands_were_processed = False
    with patch('src.main.process_commands_in_messages') as mock_process_msg:
        mock_process_msg.return_value = ([], False) # No messages, no commands processed

        with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_backend_call:
            payload = {
                "model": "some-model",
                # Messages here don't matter as process_commands_in_messages is mocked
                "messages": [{"role": "user", "content": "This will be ignored"}]
            }
            response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 400 # Bad Request
    assert "No messages provided" in response.json()["detail"]
    mock_backend_call.assert_not_called()


def test_get_openrouter_headers_no_api_key(client: TestClient):
    # Test the get_openrouter_headers helper when API key is missing
    # This is more of a unit test for the helper, but can be triggered via endpoint context

    # Temporarily unset OPENROUTER_API_KEY for this test.
    # This requires careful handling if main.py module is already loaded.
    # It's often better to test get_openrouter_headers directly as a unit test.
    # For an integration test, we'd rely on the backend call failing if headers are bad.

    # Let's simulate the backend call raising an HTTPException due to missing key from headers_provider
    # This tests the exception handling in the endpoint when the backend fails.

    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        # Simulate the kind of error that might happen if headers_provider fails or leads to OpenRouter error
        mock_method.side_effect = HTTPException(status_code=500, detail="Simulated backend error due to bad headers")

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 500
    assert "Simulated backend error due to bad headers" in response.json()["detail"]

    # If we wanted to test get_openrouter_headers directly, it would be:
    # from src.main import get_openrouter_headers, OPENROUTER_API_KEY
    # with patch('src.main.OPENROUTER_API_KEY', None):
    #     with pytest.raises(HTTPException) as exc_info:
    #         get_openrouter_headers()
    #     assert exc_info.value.status_code == 500
    #     assert "OpenRouter API key not set" in exc_info.value.detail
    # This latter part is a true unit test for get_openrouter_headers.
    # The integration test above verifies that if the backend fails (possibly due to header issues),
    # the endpoint handles it.
