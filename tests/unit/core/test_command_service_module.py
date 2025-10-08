import pytest
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_service import ensure_command_service
from src.core.interfaces.command_service_interface import ICommandService


class ConcreteCommandService(ICommandService):
    async def process_commands(
        self, messages: list[str], session_id: str
    ) -> ProcessedResult:
        return ProcessedResult(
            modified_messages=messages,
            command_executed=True,
            command_results=[session_id],
        )


@pytest.mark.asyncio
async def test_ensure_command_service_accepts_valid_service() -> None:
    service = ConcreteCommandService()

    validated_service = ensure_command_service(service)

    assert validated_service is service

    result = await validated_service.process_commands(["message"], "session")
    assert result.command_executed is True
    assert result.command_results == ["session"]
    assert result.modified_messages == ["message"]


@pytest.mark.asyncio
async def test_ensure_command_service_wraps_async_callable() -> None:
    async def handler(messages: list[str], session_id: str) -> ProcessedResult:
        return ProcessedResult(
            modified_messages=[f"{session_id}:{value}" for value in messages],
            command_executed=bool(messages),
            command_results=[session_id],
        )

    validated_service = ensure_command_service(handler)

    assert isinstance(validated_service, ICommandService)

    result = await validated_service.process_commands(["message"], "session")
    assert result.modified_messages == ["session:message"]
    assert result.command_executed is True
    assert result.command_results == ["session"]


def test_ensure_command_service_rejects_none() -> None:
    with pytest.raises(ValueError) as exc:
        ensure_command_service(None)

    assert "command service" in str(exc.value).lower()


def test_ensure_command_service_rejects_invalid_type() -> None:
    with pytest.raises(TypeError) as exc:
        ensure_command_service(object())

    assert "command service" in str(exc.value).lower()
