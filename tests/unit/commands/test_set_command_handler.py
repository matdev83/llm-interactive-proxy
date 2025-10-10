from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from src.core.commands.command import Command
from src.core.commands.handlers.set_command_handler import SetCommandHandler
from src.core.commands.parser import CommandParser
from src.core.commands.service import NewCommandService
from src.core.domain import chat as models
from src.core.domain.command_results import CommandResult
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session, SessionState


def test_set_command_handler_updates_temperature() -> None:
    handler = SetCommandHandler()
    state = SessionState(reasoning_config=ReasoningConfiguration(temperature=0.2))
    session = Session(session_id="test", state=state)
    command = Command(name="set", args={"temperature": "0.8"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert result.message == "Settings updated"
    assert session.state.reasoning_config.temperature == pytest.approx(0.8)


def test_set_command_handler_updates_project_dir(tmp_path: Path) -> None:
    handler = SetCommandHandler()
    session = Session(session_id="test", state=SessionState())
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    command = Command(name="set", args={"project-dir": str(project_dir)})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert session.state.project_dir == str(project_dir)


def test_set_command_handler_rejects_unknown_parameter() -> None:
    handler = SetCommandHandler()
    session = Session(session_id="test", state=SessionState())
    command = Command(name="set", args={"unsupported": "value"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is False
    assert result.message == "Unknown parameter: unsupported"


def test_set_command_handler_validates_temperature_range() -> None:
    handler = SetCommandHandler()
    session = Session(
        session_id="test",
        state=SessionState(reasoning_config=ReasoningConfiguration()),
    )
    command = Command(name="set", args={"temperature": "2.5"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is False
    assert result.message == "Temperature must be between 0.0 and 1.0"


@pytest.mark.asyncio
async def test_command_service_uses_session_specific_prefix_and_restores(monkeypatch):
    parser = CommandParser()
    original_prefix = parser.command_prefix

    session = Session(session_id="session", state=SessionState(command_prefix="$/"))

    class DummySessionService:
        async def get_session(self, session_id: str) -> Session:
            return session

    command_service = NewCommandService(
        session_service=DummySessionService(),
        command_parser=parser,
        strict_command_detection=False,
        app_state=None,
    )

    class DummyHandler:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def handle(self, command: Command, session: Session) -> CommandResult:
            return CommandResult(success=True, message="ok", name=command.name)

    def fake_get_command_handler(name: str):
        return DummyHandler if name == "set" else None

    monkeypatch.setattr(
        "src.core.commands.service.get_command_handler",
        fake_get_command_handler,
    )

    messages = [models.ChatMessage(role="user", content="$/set(temperature=0.5)")]
    result = await command_service.process_commands(messages, session.session_id)

    assert result.command_executed is True
    assert parser.command_prefix == original_prefix
