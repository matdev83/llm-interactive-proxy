import os
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from tests.conftest import get_backend_instance, get_session_service_from_app


@pytest.mark.parametrize("alias", ["project-dir", "dir", "project-directory"])
@pytest.mark.asyncio
async def test_set_project_dir_command_valid(client: TestClient, alias):
    """Test that project directory can be set with various aliases."""

    session_service = get_session_service_from_app(client.app)
    session = await session_service.get_session("default")
    session.state.project_dir = None

    # Get the current directory
    current_dir = os.path.abspath(os.curdir)

    backend = get_backend_instance(client.app, "openrouter")
    with patch.object(
        backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": f"!/set({alias}={current_dir})"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    session = await session_service.get_session("default")
    assert session.state.project_dir == current_dir


@pytest.mark.asyncio
async def test_set_project_dir_command_invalid(client: TestClient):
    """Test setting an invalid project directory."""

    session_service = get_session_service_from_app(client.app)
    session = await session_service.get_session("default")
    session.state.project_dir = None

    # Use a non-existent directory
    invalid_dir = "/non/existent/path"

    backend = get_backend_instance(client.app, "openrouter")
    with patch.object(
        backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "some-model",
            "messages": [
                {"role": "user", "content": f"!/set(project-dir={invalid_dir})"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert (
        "Directory '/non/existent/path' not found."
        in response_json["choices"][0]["message"]["content"]
    )


@pytest.mark.parametrize("alias", ["project-dir", "dir", "project-directory"])
@pytest.mark.asyncio
async def test_unset_project_dir_command(client: TestClient, alias):
    """Test that project directory can be unset with various aliases."""

    from src.core.commands.unset_command import UnsetCommand

    # Get a fresh session service for each test
    session_service = get_session_service_from_app(client.app)

    # Create a new session with a specific ID for this test
    test_session_id = f"test_unset_{alias}"
    session = await session_service.get_or_create_session(test_session_id)

    # Manually set the project directory
    session.state.project_dir = "/some/path"
    await session_service.update_session(session)

    # Verify the session has the path set
    session = await session_service.get_session(test_session_id)
    assert session.state.project_dir == "/some/path"

    # Apply the unset command directly to the session
    command = UnsetCommand()
    result = await command.execute({alias: True}, session)
    assert result.success is True

    # The command should have modified the session state directly
    # Get a fresh copy of the session from the repository
    session = await session_service.get_session(test_session_id)

    # Debug output
    print(f"Session ID: {test_session_id}")
    print(f"Project dir after unset: {session.state.project_dir}")

    # This should now be None
    assert session.state.project_dir is None
