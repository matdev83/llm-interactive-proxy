from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_set_project_command_integration(client: TestClient):
    payload = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "!/set(project=test-project) Hello"}],
    }
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    session_service = client.app.state.session_manager
    session = session_service.get_session("default")  # This is a sync method
    assert session.state.project == "test-project"


@pytest.mark.asyncio
async def test_unset_project_command_integration(client: TestClient):
    session_service = client.app.state.session_manager
    session = session_service.get_session("default")  # This is a sync method
    session.state.set_project("initial-project")  # Set initial project

    payload = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "!/unset(project) Settings cleared"}],
    }
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert session.state.project is None


@pytest.mark.asyncio
async def test_set_project_name_alias_integration(client: TestClient):
    payload = {
        "model": "some-model",
        "messages": [
            {"role": "user", "content": "!/set(project-name=alias-project) Query"}
        ],
    }
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    session_service = client.app.state.session_manager
    session = session_service.get_session("default")  # This is a sync method
    assert session.state.project == "alias-project"


@pytest.mark.asyncio
async def test_unset_project_name_alias_integration(client: TestClient):
    session_service = client.app.state.session_manager
    session = session_service.get_session("default")  # This is a sync method
    session.state.set_project("initial-alias-project")  # Set initial project

    payload = {
        "model": "some-model",
        "messages": [
            {"role": "user", "content": "!/unset(project-name) Settings reset"}
        ],
    }
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert session.state.project is None


@pytest.mark.asyncio
async def test_force_set_project_blocks_requests(client: TestClient):
    # Temporarily enable force_set_project for this test client's app instance
    original_force_set_project = client.app.state.force_set_project
    client.app.state.force_set_project = True
    try:
        session_service = client.app.state.session_manager
        session = session_service.get_session("default")  # This is a sync method
        session.state.unset_project()  # Ensure project is not set

        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "Hello, world!"}],
        }
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 400
        assert "Project name not set" in response.json()["error"]["message"]
    finally:
        client.app.state.force_set_project = original_force_set_project


@pytest.mark.asyncio
async def test_force_set_project_allows_after_set(client: TestClient):
    original_force_set_project = client.app.state.force_set_project
    client.app.state.force_set_project = True
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}
    try:
        with patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as mock_method:
            mock_method.return_value = mock_backend_response

            # First, set the project
            set_project_payload = {
                "model": "some-model",
                "messages": [
                    {"role": "user", "content": "!/set(project=forced-project)"}
                ],
            }
            response_set = client.post("/v1/chat/completions", json=set_project_payload)
            assert response_set.status_code == 200
            session_service = client.app.state.session_manager
            session = session_service.get_session("default")  # This is a sync method
            assert session.state.project == "forced-project"

            # Then, make a normal request
            query_payload = {
                "model": "some-model",
                "messages": [{"role": "user", "content": "Actual query now"}],
            }
            response_query = client.post("/v1/chat/completions", json=query_payload)
            assert response_query.status_code == 200
            assert response_query.json()["choices"][0]["message"]["content"] == "ok"
            mock_method.assert_called_once()  # Ensure backend was called
    finally:
        client.app.state.force_set_project = original_force_set_project
