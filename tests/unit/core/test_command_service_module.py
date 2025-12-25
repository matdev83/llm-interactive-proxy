from unittest.mock import MagicMock

import pytest
from src.core.commands.models import Command, CommandResultWrapper
from src.core.domain.chat import ChatMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_service import ensure_command_service
from src.core.interfaces.command_service_interface import ICommandService


class ConcreteCommandService(ICommandService):
    async def process_commands(
        self, messages: list[ChatMessage], session_id: str
    ) -> ProcessedResult:
        mock_result = MagicMock()
        mock_result.message = "success"
        mock_result.success = True
        return ProcessedResult(
            modified_messages=messages,
            command_executed=True,
            command_results=[CommandResultWrapper("test", mock_result)],
        )

    async def execute_command(
        self, command: Command, session_id: str
    ) -> CommandResultWrapper:
        mock_result = MagicMock()
        mock_result.message = f"executed {command.name}"
        mock_result.success = True
        return CommandResultWrapper(
            command.name,
            mock_result
        )


@pytest.mark.asyncio
async def test_ensure_command_service_accepts_valid_service() -> None:
    service = ConcreteCommandService()

    validated_service = ensure_command_service(service)

    assert validated_service is service

    msg = ChatMessage(role="user", content="message")
    result = await validated_service.process_commands([msg], "session")
    assert result.command_executed is True
    assert len(result.command_results) == 1
    assert result.modified_messages == [msg]


@pytest.mark.asyncio
async def test_ensure_command_service_wraps_async_callable() -> None:
    async def handler(messages: list[ChatMessage], session_id: str) -> ProcessedResult:
        mock_result = MagicMock()
        mock_result.message = "success"
        mock_result.success = True
        return ProcessedResult(
            modified_messages=[ChatMessage(role=m.role, content=f"{session_id}:{m.content}") for m in messages],
            command_executed=bool(messages),
            command_results=[CommandResultWrapper("test", mock_result)],
        )

    validated_service = ensure_command_service(handler)

    assert isinstance(validated_service, ICommandService)

    msg = ChatMessage(role="user", content="message")
    result = await validated_service.process_commands([msg], "session")
    assert result.modified_messages[0].content == "session:message"
    assert result.command_executed is True
    assert len(result.command_results) == 1


@pytest.mark.asyncio
async def test_ensure_command_service_wraps_sync_callable() -> None:
    def handler(messages: list[ChatMessage], session_id: str) -> ProcessedResult:
        mock_result = MagicMock()
        mock_result.message = "success"
        mock_result.success = True
        return ProcessedResult(
            modified_messages=[ChatMessage(role=m.role, content=m.content.upper()) for m in messages if isinstance(m.content, str)],
            command_executed=True,
            command_results=[CommandResultWrapper("test", mock_result)],
        )

    validated_service = ensure_command_service(handler)

    msg = ChatMessage(role="user", content="hello")
    result = await validated_service.process_commands([msg], "session")
    assert result.modified_messages[0].content == "HELLO"
    assert result.command_executed is True
    assert len(result.command_results) == 1



def test_ensure_command_service_rejects_none() -> None:
    with pytest.raises(ValueError) as exc:
        ensure_command_service(None)

    assert "command service" in str(exc.value).lower()


def test_ensure_command_service_rejects_invalid_type() -> None:
    with pytest.raises(TypeError) as exc:
        ensure_command_service(object())

    assert "command service" in str(exc.value).lower()
