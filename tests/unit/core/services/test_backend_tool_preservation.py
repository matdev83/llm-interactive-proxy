from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    ToolCall,
)
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_request_manager_service import BackendRequestManager

from tests.helpers.angel_factory_stub import AngelFactoryStub


@pytest.mark.asyncio
async def test_prepare_backend_request_preserves_tools_when_commands_run() -> None:
    backend_processor = MagicMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "do_it",
                    "description": "",
                    "parameters": {},
                },
            }
        ],
        tool_choice="auto",
        temperature=0.5,
    )

    command_result = ProcessedResult(
        modified_messages=[{"role": "user", "content": "adjusted"}],
        command_executed=True,
        command_results=[],
    )

    backend_request = await manager.prepare_backend_request(request, command_result)

    assert backend_request is not None
    assert backend_request.tools == request.tools
    assert backend_request.tool_choice == request.tool_choice
    assert backend_request.temperature == pytest.approx(request.temperature)


@pytest.mark.asyncio
async def test_backend_processor_passes_tools_to_backend() -> None:
    backend_service = AsyncMock()
    backend_service.call_completion.return_value = ResponseEnvelope(content={})

    session_state = SimpleNamespace(
        backend_config=SimpleNamespace(backend_type="openai", model="test-model"),
        project=None,
    )
    session = SimpleNamespace(state=session_state)
    session.add_interaction = MagicMock()

    session_service = AsyncMock()
    session_service.get_session.return_value = session

    app_state = MagicMock()
    app_state.get_failover_routes.return_value = []
    app_state.get_setting.return_value = None

    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "do_it",
                    "description": "",
                    "parameters": {},
                },
            }
        ],
        tool_choice="auto",
    )

    processor = BackendProcessor(backend_service, session_service, app_state)

    context = RequestContext(
        headers={}, cookies={}, state=None, app_state=None, session_id="session-1"
    )
    await processor.process_backend_request(request, "session-1", context)

    call_args = backend_service.call_completion.await_args
    assert call_args is not None
    call_request = call_args.kwargs["request"]
    assert call_request.tools == request.tools
    assert call_request.tool_choice == request.tool_choice


@pytest.mark.asyncio
async def test_prepare_backend_request_appends_chatmessage_results() -> None:
    """Command results carrying ChatMessage instances should be appended."""
    backend_processor = MagicMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_messages = [ChatMessage(role="user", content="original question")]
    request = ChatRequest(model="test-model", messages=original_messages, stream=False)

    tool_message = ChatMessage(
        role="tool", content="exit code: 0", tool_call_id="call-123"
    )
    command_result = ProcessedResult(
        modified_messages=list(original_messages),
        command_executed=True,
        command_results=[tool_message],
    )

    backend_request = await manager.prepare_backend_request(request, command_result)

    assert backend_request is not None
    assert backend_request.messages[-1].role == "tool"
    assert backend_request.messages[-1].tool_call_id == "call-123"
    assert backend_request.messages[-1].content == "exit code: 0"


class _ToolWrapper:
    """Minimal stub exposing tool_messages for command result tests."""

    def __init__(self, tool_messages: list[dict[str, Any]]) -> None:
        self.tool_messages = tool_messages


@pytest.mark.asyncio
async def test_prepare_backend_request_supports_tool_message_wrappers() -> None:
    backend_processor = MagicMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    user_message = ChatMessage(role="user", content="Do something")
    request = ChatRequest(model="test-model", messages=[user_message], stream=False)

    command_result = ProcessedResult(
        modified_messages=[user_message],
        command_executed=True,
        command_results=[
            _ToolWrapper(
                [
                    {
                        "role": "assistant",
                        "content": "tool invocation text",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": '{"command":["ls"]}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call-1",
                        "content": "output",
                    },
                ]
            )
        ],
    )

    backend_request = await manager.prepare_backend_request(request, command_result)
    assert backend_request is not None
    assert len(backend_request.messages) == 3
    assistant_msg = backend_request.messages[-2]
    tool_msg = backend_request.messages[-1]
    assert assistant_msg.role == "assistant"
    assert assistant_msg.tool_calls
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_prepare_backend_request_appends_results_without_modified_messages() -> (
    None
):
    """Verify command results are appended even if modified_messages is empty."""
    backend_processor = MagicMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_messages = [
        ChatMessage(role="user", content="question"),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-456",
                    type="function",
                    function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
                )
            ],
        ),
    ]
    request = ChatRequest(model="test-model", messages=original_messages, stream=False)

    tool_message = ChatMessage(
        role="tool", content="file.txt", tool_call_id="call-456", name="shell"
    )
    command_result = ProcessedResult(
        modified_messages=[],  # No modified messages
        command_executed=True,
        command_results=[tool_message],
    )

    backend_request = await manager.prepare_backend_request(request, command_result)

    assert backend_request is not None
    assert len(backend_request.messages) == 3
    assert backend_request.messages[0].content == "question"
    assert backend_request.messages[1].tool_calls is not None
    assert backend_request.messages[2].role == "tool"
    assert backend_request.messages[2].tool_call_id == "call-456"
    assert backend_request.messages[2].content == "file.txt"
