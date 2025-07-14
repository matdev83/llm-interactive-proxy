from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from src.main import build_app

@pytest.fixture
def client_with_config(tmp_path, monkeypatch):
    config_file = tmp_path / "test_config.json"
    config_file.touch()
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "dummy_or_key")
    monkeypatch.setenv("LLM_BACKEND", "openrouter")
    app = build_app(config_file=str(config_file))
    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        yield client

@pytest.mark.parametrize("alias", ["project-dir", "dir", "project-directory"])
def test_set_project_dir_command_valid(client_with_config: TestClient, tmp_path, alias):
    with patch.object(
        client_with_config.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        valid_dir = tmp_path.resolve()
        payload = {
            "model": "some-model",
            "messages": [
                {
                    "role": "user",
                    "content": f'!/set({alias}="{valid_dir}")'
                }
            ],
        }
        response = client_with_config.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    session = client_with_config.app.state.session_manager.get_session("default")
    assert session.proxy_state.project_dir == str(valid_dir)


def test_set_project_dir_command_invalid(client: TestClient):
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "some-model",
            "messages": [
                {
                    "role": "user",
                    "content": '!/set(project-dir="/non/existent/path")'
                }
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert "Directory '/non/existent/path' not found." in response_json["choices"][0]["message"]["content"]

@pytest.mark.parametrize("alias", ["project-dir", "dir", "project-directory"])
def test_unset_project_dir_command(client: TestClient, alias):
    session = client.app.state.session_manager.get_session("default")
    session.proxy_state.project_dir = "/some/path"

    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "some-model",
            "messages": [
                {
                    "role": "user",
                    "content": f"!/unset({alias})"
                }
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert session.proxy_state.project_dir is None
