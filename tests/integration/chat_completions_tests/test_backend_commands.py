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


def test_set_backend_command_integration(client: TestClient):
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(app.state.gemini_backend, 'chat_completions', new_callable=AsyncMock) as gem_mock, \
         patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as open_mock:
        gem_mock.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/set(backend=gemini) hi"}]
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    gem_mock.assert_called_once()
    open_mock.assert_not_called()
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_backend == "gemini"
    assert response.json()["choices"][0]["message"]["content"] == "ok"


def test_unset_backend_command_integration(client: TestClient):
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    session.proxy_state.set_override_backend("gemini")
    mock_backend_response = {"choices": [{"message": {"content": "done"}}]}
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as open_mock:
        open_mock.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/unset(backend) hi"}]
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    open_mock.assert_called_once()
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_backend is None
    assert response.json()["choices"][0]["message"]["content"] == "done"
