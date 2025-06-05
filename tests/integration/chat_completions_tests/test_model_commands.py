import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from httpx import Response
from starlette.responses import StreamingResponse
from fastapi import HTTPException, FastAPI # Import FastAPI for type hinting

from src.main import app, get_openrouter_headers
import src.models as models
from src.session_manager import SessionManager
# import src.main # No longer needed to access module-level proxy_state

@pytest.fixture
def client():
    with TestClient(app) as c:
        c.app.state.session_manager = SessionManager(ttl_seconds=1000)  # type: ignore
        yield c

def test_set_model_command_integration(client: TestClient):
    mock_backend_response = {"choices": [{"message": {"content": "Model set and called."}}]}

    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        session = client.app.state.session_manager.get_session(None, "test")
        payload = {
            "model": "original-model",
            "messages": [{"role": "user", "content": "Use this: !/set(model=override-model) Hello"}]
        }
        response = client.post("/v1/chat/completions", json=payload, headers={"X-Session-ID": session.session_id})

    assert response.status_code == 200
    assert response.headers["X-Session-ID"] == session.session_id
    assert client.app.state.session_manager.sessions[session.session_id].proxy_state.override_model == "override-model"  # type: ignore

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['request_data'].model == "original-model"
    assert call_args['effective_model'] == "override-model"
    assert call_args['processed_messages'][0].content == "Use this: Hello"


def test_unset_model_command_integration(client: TestClient):
    session = client.app.state.session_manager.get_session(None, "test")
    session.proxy_state.set_override_model("initial-override")

    mock_backend_response = {"choices": [{"message": {"content": "Model unset and called."}}]}

    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response

        payload = {
            "model": "another-model",
            "messages": [{"role": "user", "content": "Please !/unset(model) use default."}]
        }
        response = client.post("/v1/chat/completions", json=payload, headers={"X-Session-ID": session.session_id})

    assert response.status_code == 200
    assert response.headers["X-Session-ID"] == session.session_id
    assert client.app.state.session_manager.sessions[session.session_id].proxy_state.override_model is None  # type: ignore

    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args['effective_model'] == "another-model"
    assert call_args['processed_messages'][0].content == "Please use default."
