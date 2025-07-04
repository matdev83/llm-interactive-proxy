import pytest
from unittest.mock import AsyncMock, patch

from httpx import Response
from starlette.responses import StreamingResponse
from fastapi import HTTPException

import src.models as models

def test_empty_messages_after_processing_no_commands_bad_request(client):
    with patch('src.command_parser.CommandParser.process_messages') as mock_process_msg:
        mock_process_msg.return_value = ([], False) # Simulate messages becoming empty, no commands processed

        with patch.object(client.app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_backend_call:
            payload = {
                "model": "some-model",
                "messages": [{"role": "user", "content": "This will be ignored"}] # Original messages
            }
            response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 400
    assert "No messages provided" in response.json()["detail"] # Check specific detail message
    mock_backend_call.assert_not_called()


def test_get_openrouter_headers_no_api_key(client):
    # This test seems to be testing an internal error rather than a direct API key issue from client side.
    # It mocks chat_completions to raise an error, implying headers might be bad.
    # If the goal is to test what happens if get_openrouter_headers itself fails or returns bad headers,
    # that would need a different mocking strategy (e.g., mock get_openrouter_headers).
    # For now, assuming the test is as intended:
    with patch.object(client.app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        # Simulate an error that might occur if headers were bad leading to backend failure
        mock_method.side_effect = HTTPException(status_code=500, detail="Simulated backend error (e.g. due to bad headers)")

        payload = {
            "model": "gpt-3.5-turbo", # A model that would use OpenRouter
            "messages": [{"role": "user", "content": "Hello"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 500
    assert "Simulated backend error (e.g. due to bad headers)" in response.json()["detail"]


def test_invalid_model_noninteractive(client):
    client.app.state.openrouter_backend.available_models = [] # Ensure 'bad' model is not in list
    # Disable interactive mode for this session if it's not default
    session = client.app.state.session_manager.get_session("test_invalid_model_noninteractive_session")
    session.proxy_state.interactive_mode = False

    payload = {
        "model": "m", # Initial model, will be overridden by command
        "messages": [{"role": "user", "content": "!/set(model=openrouter:bad)"}],
    }
    resp = client.post("/v1/chat/completions", json=payload, headers={"x-session-id": "test_invalid_model_noninteractive_session"})
    assert resp.status_code == 200
    response_content = resp.json()["choices"][0]["message"]["content"]
    # The command is processed, message becomes empty, so it's a command-only response.
    # The content will be the result of the set command ("Settings updated.") wrapped.
    assert "Settings updated." in response_content
    # Also check for agent wrapping if applicable (depends on default agent or if one was set)
    # For this test, primarily concerned that it doesn't say "Proxy command processed" without a reason.

    # Now, try to use the 'bad' model set in the previous request (non-interactive, so it was allowed to be set)
    payload2 = {
        "model": "m", # This will be overridden by the session state's override_model
        "messages": [{"role": "user", "content": "Hello"}],
    }
    resp2 = client.post("/v1/chat/completions", json=payload2, headers={"x-session-id": "test_invalid_model_noninteractive_session"})
    assert resp2.status_code == 400
    # Check the error detail structure for invalid model
    error_detail = resp2.json()["detail"]
    assert isinstance(error_detail, dict)
    assert error_detail.get("message") == "invalid or unsupported model"
    assert error_detail.get("model") == "openrouter:bad"
    # Clean up session for other tests if necessary, though pytest usually isolates
    client.app.state.session_manager.sessions.pop("test_invalid_model_noninteractive_session", None)
