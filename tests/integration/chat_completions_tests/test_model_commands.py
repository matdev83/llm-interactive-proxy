import pytest
from unittest.mock import AsyncMock, patch

from httpx import Response
from starlette.responses import StreamingResponse
from fastapi import HTTPException, FastAPI # Import FastAPI for type hinting

import src.models as models
# import src.main # No longer needed to access module-level proxy_state

def test_set_model_command_integration(client):
    mock_backend_response = {"choices": [{"message": {"content": "Model set and called."}}]}

    with patch.object(client.app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        client.app.state.openrouter_backend.available_models = ["override-model"]
        payload = {
            "model": "original-model",
            "messages": [{"role": "user", "content": "Use this: !/set(model=openrouter:override-model) Hello"}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    # Access proxy_state from the app state within the test client
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_model == "override-model"

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['request_data'].model == "original-model"
    assert call_args['effective_model'] == "override-model"
    assert call_args['processed_messages'][0].content == "Use this: Hello"


def test_unset_model_command_integration(client):
    # Access proxy_state from the app state within the test client
    client.app.state.session_manager.get_session("default").proxy_state.set_override_model("openrouter", "initial-override")  # type: ignore

    mock_backend_response = {"choices": [{"message": {"content": "Model unset and called."}}]}

    with patch.object(client.app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        client.app.state.openrouter_backend.available_models = ["another-model"]
        payload = {
            "model": "another-model",
            "messages": [{"role": "user", "content": "Please !/unset(model) use default."}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    # Access proxy_state from the app state within the test client
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_model is None

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['effective_model'] == "another-model"
    assert call_args['processed_messages'][0].content == "Please use default."
