import json
from unittest.mock import AsyncMock

import pytest
from src.core.domain.configuration.dangerous_command_config import (
    DEFAULT_DANGEROUS_COMMAND_CONFIG,
)
from src.core.domain.responses import ProcessedResponse
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.dangerous_command_service import DangerousCommandService
from src.core.services.tool_call_handlers.dangerous_command_handler import (
    DangerousCommandHandler,
)
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware


class FakeReactor:
    def __init__(self) -> None:
        self.process_tool_call = AsyncMock()
        self._handlers: list[str] = []

    def get_registered_handlers(self) -> list[str]:
        return self._handlers


@pytest.mark.asyncio
async def test_reactor_swallows_dangerous_command_and_steers() -> None:
    reactor = FakeReactor()
    middleware = ToolCallReactorMiddleware(reactor, enabled=True)

    dangerous_tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "execute_command",
            "arguments": json.dumps({"command": "git reset --hard"}),
        },
    }
    content = json.dumps(
        {"choices": [{"message": {"tool_calls": [dangerous_tool_call]}}]}
    )
    response = ProcessedResponse(content=content)

    # Emulate handler decision: swallow with steering message
    from src.core.interfaces.tool_call_reactor_interface import ToolCallReactionResult

    reactor.process_tool_call.return_value = ToolCallReactionResult(
        should_swallow=True, replacement_response="steering", metadata={}
    )

    result = await middleware.process(
        response,
        session_id="s1",
        context={"backend_name": "openai", "model_name": "gpt-4"},
    )

    assert isinstance(result, ProcessedResponse)
    assert result.content == "steering"


@pytest.mark.asyncio
async def test_dangerous_command_handler_detection() -> None:
    handler = DangerousCommandHandler(
        DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
    )
    ctx = ToolCallContext(
        session_id="s",
        backend_name="openai",
        model_name="gpt-4",
        full_response="",
        tool_name="bash",
        tool_arguments={"command": "git push --force"},
    )
    assert await handler.can_handle(ctx) is True
    res = await handler.handle(ctx)
    assert res.should_swallow is True


@pytest.mark.asyncio
async def test_dangerous_command_handler_custom_message() -> None:
    custom = "Custom steering message"
    handler = DangerousCommandHandler(
        DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG),
        steering_message=custom,
    )
    ctx = ToolCallContext(
        session_id="s",
        backend_name="openai",
        model_name="gpt-4",
        full_response="",
        tool_name="bash",
        tool_arguments={"command": "git push --force"},
    )
    res = await handler.handle(ctx)
    assert res.should_swallow is True
    assert res.replacement_response == custom
