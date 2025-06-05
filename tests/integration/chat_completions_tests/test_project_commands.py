import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.main import app
from src.session import SessionManager

@pytest.fixture
def client():
    with TestClient(app) as c:
        c.app.state.session_manager = SessionManager()  # type: ignore
        yield c


def test_set_project_command_integration(client: TestClient):
    mock_backend_response = {"choices": [{"message": {"content": "Project set"}}]}
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/set(project='proj x') hi"}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.project == "proj x"
    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args["project"] == "proj x"
    assert call_args["processed_messages"][0].content == "hi"


def test_unset_project_command_integration(client: TestClient):
    client.app.state.session_manager.get_session("default").proxy_state.set_project("initial")  # type: ignore
    mock_backend_response = {"choices": [{"message": {"content": "unset"}}]}
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "please !/unset(project)"}]
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.project is None
    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args["project"] is None
    assert call_args["processed_messages"][0].content == "please"

