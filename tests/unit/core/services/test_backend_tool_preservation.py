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
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    IResponseProcessor,
    ProcessedResponse,
)


@pytest.mark.asyncio
async def test_prepare_backend_request_preserves_tools_when_commands_run() -> None:
    backend_processor = MagicMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(backend_processor, response_processor)

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

    context = SimpleNamespace(session_id="session-1")
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
    manager = BackendRequestManager(backend_processor, response_processor)

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
    manager = BackendRequestManager(backend_processor, response_processor)

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
    manager = BackendRequestManager(backend_processor, response_processor)

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


class _StubBackendProcessor:
    async def process_backend_request(self, *args: Any, **kwargs: Any) -> ResponseEnvelope:
        return ResponseEnvelope(content="raw", metadata={})


class _StubResponseProcessor(IResponseProcessor):
    async def process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        return ProcessedResponse(content="processed", metadata={"source": "processor"})

    def process_streaming_response(self, response_iterator, session_id: str):  # type: ignore[override]
        raise NotImplementedError

    async def register_middleware(self, middleware: IResponseMiddleware, priority: int = 0) -> None:
        return None


class _StubStructuredMiddleware(IResponseMiddleware):
    def __init__(self) -> None:
        super().__init__(priority=5)
        self.calls = 0

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        self.calls += 1
        return ProcessedResponse(
            content="structured",
            metadata={"structured_output_validated": True, "schema_validation_attempted": True},
        )


@pytest.mark.asyncio
async def test_backend_request_manager_uses_injected_structured_output_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_get_service_provider() -> None:
        raise RuntimeError("global service provider should not be used")

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        _fail_get_service_provider,
    )

    structured_middleware = _StubStructuredMiddleware()
    manager = BackendRequestManager(
        _StubBackendProcessor(),
        _StubResponseProcessor(),
        structured_output_middleware=structured_middleware,
    )

    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    context = SimpleNamespace(
        processing_context={
            "response_schema": {"type": "object"},
            "schema_name": "schema",
            "request_id": "req-1",
        }
    )

    response = await manager.process_backend_request(request, "session-1", context)

    assert structured_middleware.calls == 1
    assert response.content == "structured"
    assert response.metadata is not None
    assert response.metadata.get("structured_output_validated") is True
    assert response.metadata.get("schema_validation_attempted") is True
