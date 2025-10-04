from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest
from src.core.commands.command import Command
from src.core.commands.handlers.set_command_handler import SetCommandHandler
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session, SessionState
from src.core.interfaces.command_service_interface import ICommandService


def test_set_command_handler_updates_temperature() -> None:
    mock_command_service = Mock(spec=ICommandService)
    handler = SetCommandHandler(command_service=mock_command_service)
    state = SessionState(reasoning_config=ReasoningConfiguration(temperature=0.2))
    session = Session(session_id="test", state=state)
    command = Command(name="set", args={"temperature": "0.8"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert result.message == "Settings updated"
    assert session.state.reasoning_config.temperature == pytest.approx(0.8)


def test_set_command_handler_updates_project_dir(tmp_path: Path) -> None:
    mock_command_service = Mock(spec=ICommandService)
    handler = SetCommandHandler(command_service=mock_command_service)
    session = Session(session_id="test", state=SessionState())
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    command = Command(name="set", args={"project-dir": str(project_dir)})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert session.state.project_dir == str(project_dir)


def test_set_command_handler_rejects_unknown_parameter() -> None:
    mock_command_service = Mock(spec=ICommandService)
    handler = SetCommandHandler(command_service=mock_command_service)
    session = Session(session_id="test", state=SessionState())
    command = Command(name="set", args={"unsupported": "value"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is False
    assert result.message == "Unknown parameter: unsupported"


def test_set_command_handler_validates_temperature_range() -> None:
    mock_command_service = Mock(spec=ICommandService)
    handler = SetCommandHandler(command_service=mock_command_service)
    session = Session(
        session_id="test",
        state=SessionState(reasoning_config=ReasoningConfiguration()),
    )
    command = Command(name="set", args={"temperature": "2.5"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is False
    assert result.message == "Temperature must be between 0.0 and 1.0"
