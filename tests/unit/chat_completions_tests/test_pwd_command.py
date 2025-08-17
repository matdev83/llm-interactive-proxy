from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.interfaces.session_service import ISessionService


@pytest.mark.asyncio
async def test_pwd_command_with_project_dir_set(client: TestClient):
    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    session = await session_service.get_session("default")
    session.state.project_dir = "/test/project/dir"

    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
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
    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    session = await session_service.get_session("default")
    session.state.project_dir = None

    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
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
