"""Unit tests for the command result wrapper scoping bug."""

from __future__ import annotations

from typing import Any

import pytest
from src.core.commands.handler import ICommandHandler
from src.core.commands.models import Command, CommandResultWrapper
from src.core.commands.parser import CommandParser
from src.core.domain.chat import ChatMessage
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session


class _StubSessionService:
    async def get_session(self, session_id: str) -> Session:
        return Session(session_id=session_id)

    async def update_session(
        self, session: Session
    ) -> None:  # pragma: no cover - interface stub
        return None


class _DummyHandler(ICommandHandler):
    @property
    def command_name(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "mock handler"

    @property
    def format(self) -> str:
        return "mock()"

    @property
    def examples(self) -> list[str]:
        return ["!/mock()"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        return CommandResult(success=True, message="done", name=command.name)


@pytest.mark.asyncio
async def test_command_result_wrapper_type_is_stable(monkeypatch: Any) -> None:
    """Ensure the wrapper class is shared across invocations for type checks."""

    from tests.utils.command_service_utils import build_new_command_service

    service = build_new_command_service(_StubSessionService(), CommandParser())

    def _get_command_handler(name: str) -> type[ICommandHandler] | None:
        return _DummyHandler if name == "mock" else None

    monkeypatch.setattr(
        "src.core.commands.service.get_command_handler", _get_command_handler
    )

    messages_one = [ChatMessage(role="user", content="!/mock()")]
    messages_two = [ChatMessage(role="user", content="!/mock()")]

    result_one = await service.process_commands(messages_one, session_id="s1")
    result_two = await service.process_commands(messages_two, session_id="s1")

    wrapper_one = result_one.command_results[0]
    wrapper_two = result_two.command_results[0]

    assert isinstance(wrapper_one, CommandResultWrapper)
    assert type(wrapper_one) is CommandResultWrapper
    assert type(wrapper_one) is type(wrapper_two)
    assert wrapper_one.message == "done"
    assert wrapper_one.name == "mock"
