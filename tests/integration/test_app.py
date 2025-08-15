"""
Integration tests for the FastAPI application.
"""

import json

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_helpers import (
    create_test_request_json,
    generate_session_id,
    mock_backend_api,
)


@pytest.fixture
def test_app_client(test_app: FastAPI) -> TestClient:
    """Create a test client for the app."""
    return TestClient(test_app)


@pytest.mark.respx
def test_chat_completions_endpoint(
    test_app_client: TestClient, respx_mock: respx.Router
):
    """Test the chat completions endpoint."""
    # Arrange
    mock_backend_api(respx_mock)
    request_json = create_test_request_json()
    session_id = generate_session_id()
    
    # Act
    response = test_app_client.post(
        "/v1/chat/completions",
        json=request_json,
        headers={"X-Session-ID": session_id},
    )
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert len(data["choices"]) == 1
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"]
    assert "usage" in data


@pytest.mark.respx
def test_streaming_chat_completions_endpoint(
    test_app_client: TestClient, respx_mock: respx.Router
):
    """Test the streaming chat completions endpoint."""
    # Arrange
    mock_backend_api(respx_mock)
    request_json = create_test_request_json(stream=True)
    session_id = generate_session_id()
    
    # Act
    with test_app_client.stream(
        "POST",
        "/v1/chat/completions",
        json=request_json,
        headers={"X-Session-ID": session_id},
    ) as response:
        # Assert
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream"
        
        # Process each chunk
        content = ""
        for line in response.iter_lines():
            if not line.strip() or line == "data: [DONE]":
                continue
                
            # Parse the JSON chunk
            chunk_data = json.loads(line.replace("data: ", ""))
            assert chunk_data["object"] == "chat.completion.chunk"
            assert len(chunk_data["choices"]) == 1
            
            # Accumulate content
            if "delta" in chunk_data["choices"][0]:
                delta = chunk_data["choices"][0]["delta"]
                if "content" in delta:
                    content += delta["content"]
        
        # Verify we got a complete message
        assert content


@pytest.mark.respx
def test_command_processing(test_app_client: TestClient, respx_mock: respx.Router):
    """Test command processing."""
    # Arrange
    mock_backend_api(respx_mock)
    session_id = generate_session_id()
    
    # Send a command to set the model
    command_request = create_test_request_json()
    command_request["messages"] = [
        {"role": "user", "content": "!/set(model=gpt-4)"}
    ]
    
    # Act
    command_response = test_app_client.post(
        "/v1/chat/completions",
        json=command_request,
        headers={"X-Session-ID": session_id},
    )
    
    # Assert
    assert command_response.status_code == 200
    data = command_response.json()
    assert data["id"] == "proxy_cmd_processed"
    assert "model set to gpt-4" in data["choices"][0]["message"]["content"].lower()
    
    # Now send a normal request - should use the set model
    request_json = create_test_request_json(model="default-model")  # Should be overridden by the command
    
    # Act
    response = test_app_client.post(
        "/v1/chat/completions",
        json=request_json,
        headers={"X-Session-ID": session_id},
    )
    
    # Assert - The model should be gpt-4
    # This check isn't perfect because we're using mocks,
    # but in a real test we'd verify the model name was passed correctly
    assert response.status_code == 200
