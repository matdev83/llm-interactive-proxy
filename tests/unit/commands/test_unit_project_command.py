"""Unit tests for ProjectCommand."""

from __future__ import annotations

import pytest
from src.core.domain.commands.project_command import ProjectCommand
from src.core.domain.session import SessionState


class _Session:
    """Lightweight session stub for testing."""

    def __init__(self) -> None:
        self.state = SessionState()


@pytest.mark.asyncio
async def test_project_command_rejects_whitespace_name() -> None:
    """Project command should reject whitespace-only project names."""

    command = ProjectCommand()
    session = _Session()

    result = await command.execute({"name": "   "}, session)

    assert result.success is False
    assert result.message == "Project name must be specified"


@pytest.mark.asyncio
async def test_project_command_trims_project_name() -> None:
    """Project command should trim and persist the provided project name."""

    command = ProjectCommand()
    session = _Session()

    result = await command.execute({"name": "  demo-project  "}, session)

    assert result.success is True
    assert result.data == {"project": "demo-project"}
    assert result.new_state is not None
    assert result.new_state.project == "demo-project"
