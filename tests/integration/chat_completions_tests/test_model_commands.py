import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from httpx import Response
from starlette.responses import StreamingResponse
from fastapi import HTTPException, FastAPI # Import FastAPI for type hinting

from src.main import app, get_openrouter_headers
import src.models as models
from src.proxy_logic import ProxyState # Import ProxyState class
# import src.main # No longer needed to access module-level proxy_state

@pytest.fixture
def client():
    # Use TestClient and set a new ProxyState instance in app.state for each test
    with TestClient(app) as c:
        # Set a new instance in app.state
        c.app.state.proxy_state = ProxyState() # type: ignore
        yield c

def test_set_model_command_integration(client: TestClient):
    mock_backend_response = {"choices": [{"message": {"content": "Model set and called."}}]}

    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        payload = {
            "model": "original-model",
            "messages": [{"role": "user", "content": "Use this: !/set(model=override-model) Hello"}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    # Access proxy_state from the app state within the test client
    assert client.app.state.proxy_state.override_model == "override-model" # type: ignore

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['request_data'].model == "original-model"
    assert call_args['effective_model'] == "override-model"
    assert call_args['processed_messages'][0].content == "Use this: Hello"


def test_unset_model_command_integration(client: TestClient):
    # Access proxy_state from the app state within the test client
    client.app.state.proxy_state.set_override_model("initial-override") # type: ignore

    mock_backend_response = {"choices": [{"message": {"content": "Model unset and called."}}]}

    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        payload = {
            "model": "another-model",
            "messages": [{"role": "user", "content": "Please !/unset(model) use default."}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    # Access proxy_state from the app state within the test client
    assert client.app.state.proxy_state.override_model is None # type: ignore

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['effective_model'] == "another-model"
    assert call_args['processed_messages'][0].content == "Please use default."
