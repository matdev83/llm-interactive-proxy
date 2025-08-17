import os
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from src.core.interfaces.session_service import ISessionService


@pytest.mark.asyncio
async def test_set_project_dir_command_valid(client: TestClient, alias):
    """Test that project directory can be set with various aliases."""
    from src.core.interfaces.session_service import ISessionService

    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    session = await session_service.get_session("default")
    session.state.project_dir = None

    # Get the current directory
    current_dir = os.path.abspath(os.curdir)

    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
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
    from src.core.interfaces.session_service import ISessionService

    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    session = await session_service.get_session("default")
    session.state.project_dir = None

    # Use a non-existent directory
    invalid_dir = "/non/existent/path"

    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": f"!/set(project-dir={invalid_dir})"}],
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
    from src.core.interfaces.session_service import ISessionService
    from src.core.domain.session import SessionState, SessionStateAdapter
    from src.core.commands.handlers.unset_handler import UnsetCommandHandler

    # Get a fresh session service for each test
    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    
    # Create a new session with a specific ID for this test
    test_session_id = f"test_unset_{alias}"
    session = await session_service.get_session(test_session_id)
    
    # Create a fresh state with project_dir set
    state = SessionState(project_dir="/some/path")
    adapter = SessionStateAdapter(state)
    
    # Manually set the session state to ensure it's properly set
    session.state = adapter
    await session_service.update_session(session)
    
    # Verify the session has the path set
    session = await session_service.get_session(test_session_id)
    assert session.state.project_dir == "/some/path"
    
    # Apply the unset command directly to the session
    handler = UnsetCommandHandler()
    result = handler.handle([alias], {}, session.state)
    assert result.success is True
    
    # Update the session with the new state
    session.state = result.new_state
    await session_service.update_session(session)

    # Get a fresh copy of the session from the repository
    session = await session_service.get_session(test_session_id)
    
    # Debug output
    print(f"Session ID: {test_session_id}")
    print(f"Project dir after unset: {session.state.project_dir}")
    print(f"Session state type: {type(session.state)}")
    print(f"Session state._state type: {type(getattr(session.state, '_state', None))}")
    
    # This should now be None
    assert session.state.project_dir is None