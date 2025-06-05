import pytest
from unittest.mock import AsyncMock, patch

from httpx import Response # For constructing mock client responses if needed by TestClient directly
from starlette.responses import StreamingResponse # If we need to mock this directly
from fastapi import HTTPException # Import HTTPException

import src.models as models # For constructing request payloads

# --- Test Cases ---

def test_basic_request_proxying_non_streaming(client):
    mock_backend_response = {
        "id": "comp-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-3.5-turbo",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello from mock backend!"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21}
    }

    # Patch the 'chat_completions' method of the OpenRouterBackend instance
    # that is stored in client.app.state.openrouter_backend
    with patch.object(client.app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
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
    assert call_args['key_name'].startswith("OPENROUTER_API_KEY")
    assert call_args['api_key'] is not None


@pytest.mark.asyncio # For using async capabilities if needed, though TestClient is sync
async def test_basic_request_proxying_streaming(client):
    # Simulate a streaming response from the backend mock
    async def mock_stream_gen():
        yield b"data: chunk1\n\n"
        yield b"data: chunk2\n\n"
        yield b"data: [DONE]\n\n"

    # The backend's chat_completions method should return a StreamingResponse
    mock_streaming_response = StreamingResponse(mock_stream_gen(), media_type="text/event-stream")

    with patch.object(client.app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_streaming_response

        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Stream test"}],
            "stream": True
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert "charset=utf-8" in response.headers["content-type"]

    # Consume the stream from the TestClient response
    stream_content = b""
    for chunk in response.iter_bytes(): # Use iter_bytes for TestClient
        stream_content += chunk

    assert stream_content == b"data: chunk1\n\ndata: chunk2\n\ndata: [DONE]\n\n"

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['request_data'].stream is True
    assert call_args['key_name'].startswith("OPENROUTER_API_KEY")
    assert call_args['api_key'] is not None
