"""Additional tests for ProjectDirCommandHandler handling of expanded paths."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from src.core.commands.handlers.base_handler import CommandHandlerResult
from src.core.commands.handlers.project_dir_handler import ProjectDirCommandHandler
from src.core.interfaces.domain_entities_interface import ISessionState


@pytest.fixture
def handler() -> ProjectDirCommandHandler:
    """Create a ProjectDirCommandHandler instance for tests."""
    return ProjectDirCommandHandler()


@pytest.fixture
def mock_state() -> ISessionState:
    """Create a mock session state that echoes updates."""
    state = Mock(spec=ISessionState)
    state.with_project_dir = Mock(return_value=state)
    return state


@pytest.mark.asyncio
async def test_handle_with_tilde_path(
    handler: ProjectDirCommandHandler,
    mock_state: ISessionState,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure paths using ~ are expanded before validation and storage."""
    project_dir = tmp_path / "tilde_project"
    project_dir.mkdir()

    # Set both HOME and USERPROFILE for Windows compatibility
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    result = handler.handle("~/tilde_project", mock_state)

    assert isinstance(result, CommandHandlerResult)
    assert result.success is True
    # Normalize paths for cross-platform compatibility
    expected_path = os.path.normpath(str(project_dir))
    actual_path = os.path.normpath(
        result.message.replace("Project directory set to ", "")
    )
    assert actual_path == expected_path
    # Mock was called with the actual expanded path (may have different separators)
    mock_state.with_project_dir.assert_called_once()
    called_path = os.path.normpath(mock_state.with_project_dir.call_args[0][0])
    assert called_path == expected_path
