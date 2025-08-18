from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import get_backend_instance, get_session_service_from_app


@pytest.mark.asyncio
async def test_pwd_command_with_project_dir_set(client: TestClient):
    session_service = get_session_service_from_app(client.app)
    session = await session_service.get_session("default")
    session.state.project_dir = "/test/project/dir"

    backend = get_backend_instance(client.app, "openrouter")
    with patch.object(
        backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/pwd"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["choices"][0]["message"]["content"] == "/test/project/dir"


@pytest.mark.asyncio
async def test_pwd_command_without_project_dir_set(client: TestClient):
    session_service = get_session_service_from_app(client.app)
    session = await session_service.get_session("default")
    session.state.project_dir = None

    backend = get_backend_instance(client.app, "openrouter")
    with patch.object(
        backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/pwd"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert (
        "Project directory not set."
        in response_json["choices"][0]["message"]["content"]
    )
