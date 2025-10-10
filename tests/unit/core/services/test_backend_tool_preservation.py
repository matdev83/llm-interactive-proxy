from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_request_manager_service import BackendRequestManager


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
