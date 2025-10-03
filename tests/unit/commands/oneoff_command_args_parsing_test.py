from __future__ import annotations

import asyncio
from unittest.mock import Mock

from src.core.domain.commands.oneoff_command import OneoffCommand
from src.core.domain.session import BackendConfiguration, Session, SessionState


def _make_command_and_session() -> tuple[OneoffCommand, Session]:
    command = OneoffCommand()
    session = Mock(spec=Session)
    session.state = SessionState(backend_config=BackendConfiguration())
    return command, session


def test_oneoff_accepts_element_arg() -> None:
    command, session = _make_command_and_session()

    result = asyncio.run(command.execute({"element": "openrouter/gpt-4"}, session))

    assert result.success is True
    assert session.state.backend_config.oneoff_backend == "openrouter"
    assert session.state.backend_config.oneoff_model == "gpt-4"


def test_oneoff_accepts_value_arg() -> None:
    command, session = _make_command_and_session()

    result = asyncio.run(command.execute({"value": "gemini:gemini-pro"}, session))

    assert result.success is True
    assert session.state.backend_config.oneoff_backend == "gemini"
    assert session.state.backend_config.oneoff_model == "gemini-pro"
