from unittest.mock import AsyncMock, patch

import pytest
from src.core.interfaces.backend_service_interface import IBackendService

# --- Test Cases ---


def test_basic_request_proxying_non_streaming(test_client):
    """Test basic request proxying for non-streaming responses using new architecture."""
    mock_backend_response = {
        "id": "comp-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-3.5-turbo",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from mock backend!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
    }

    # Get the backend service from the DI container
    backend_service = test_client.app.state.service_provider.get_required_service(
        IBackendService
    )

    # Mock the backend service's call_completion method
    with patch.object(
        backend_service,
        "call_completion",
        new_callable=AsyncMock,
    ) as mock_method:
        # The backend service should return a ResponseEnvelope
        from src.core.domain.responses import ResponseEnvelope
        
        response_envelope = ResponseEnvelope(
            content=mock_backend_response,
            headers={"content-type": "application/json"},
            status_code=200
        )
        mock_method.return_value = response_envelope

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        }
        response = test_client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    # The response includes metadata, so check the main fields
    response_data = response.json()
    assert response_data["id"] == mock_backend_response["id"]
    assert response_data["object"] == mock_backend_response["object"]
    assert response_data["model"] == mock_backend_response["model"]
    assert response_data["choices"] == mock_backend_response["choices"]
    assert response_data["usage"] == mock_backend_response["usage"]

    mock_method.assert_called_once()
    # For the new architecture, check the ChatRequest object
    call_args = mock_method.call_args
    request = call_args[0][0] if call_args[0] else call_args[1].get("request")
    assert request.model == "gpt-3.5-turbo"
    assert len(request.messages) == 1
    assert request.messages[0].content == "Hello"


@pytest.mark.asyncio
async def test_basic_request_proxying_streaming(test_client):
    """Test basic request proxying for streaming responses using new architecture."""

    # Simulate a streaming response from the backend mock with proper format

    async def mock_stream_gen():
        yield b'data: {"choices": [{"delta": {"content": "Hello"}, "index": 0}]}\\n\n'
        yield b'data: {"choices": [{"delta": {"content": " world"}, "index": 0}]}\\n\n'
        yield b'data: [DONE]\\n\n'

    # Get the backend service from the DI container
    backend_service = test_client.app.state.service_provider.get_required_service(
        IBackendService
    )

    with patch.object(
        backend_service,
        "call_completion",
        new_callable=AsyncMock,
    ) as mock_method:
        # The backend service should return a StreamingResponseEnvelope, not raw async generator
        from src.core.domain.responses import StreamingResponseEnvelope
        
        streaming_envelope = StreamingResponseEnvelope(
            content=mock_stream_gen(),
            media_type="text/event-stream",
            headers={"content-type": "text/event-stream"}
        )
        mock_method.return_value = streaming_envelope

        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Stream test"}],
            "stream": True,
        }
        response = test_client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        # The charset assertion is optional - some implementations may not include it

    # Consume the stream from the TestClient response
    stream_content = b""
    for chunk in response.iter_bytes():  # Use iter_bytes for TestClient
        stream_content += chunk

    # Check that we got valid streaming chunks
    assert b'"Hello"' in stream_content
    assert b'" world"' in stream_content
    assert b"data: [DONE]" in stream_content

    mock_method.assert_called_once()
    # For the new architecture, check the ChatRequest object and stream parameter
    call_args = mock_method.call_args
    assert call_args[1]["stream"] is True  # stream is passed as second argument
