from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest, FunctionCall, ToolCall
from src.core.domain.tool_progress_loop import (
    ToolProgressLoopAction,
    ToolProgressLoopDecision,
)
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.services.request_processor_service import RequestProcessor

from tests.unit.core.request_processor_test_support import (
    MockRequestContext,
    create_request_processor_mocks,
)
from tests.unit.core.test_doubles import MockCommandProcessor


def _tool_followup_request() -> ChatRequest:
    return ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="inspect logs"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(
                            name="read",
                            arguments='{"filePath":"var/logs/proxy.log"}',
                        ),
                    )
                ],
            ),
            ChatMessage(role="tool", content="same output", tool_call_id="call_1"),
        ],
    )


def _processor_with_guard(
    request_data: ChatRequest, guard: AsyncMock
) -> tuple[RequestProcessor, AsyncMock]:
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()
    session = AsyncMock(id="test-session", agent=None)
    session_manager.resolve_session_id.return_value = "stable-session"

    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    session_enricher.enrich.return_value = (session, request_data)  # type: ignore[attr-defined]

    app_state = MagicMock(spec=IApplicationState)
    app_state.get_backend_type.return_value = "openai"
    app_state.get_setting.return_value = None

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=app_state,
        tool_progress_loop_guard=guard,
    )
    return processor, backend_executor  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_tool_progress_guard_blocks_before_backend_dispatch() -> None:
    request_data = _tool_followup_request()
    guard = AsyncMock()
    guard.evaluate_request.return_value = ToolProgressLoopDecision(
        action=ToolProgressLoopAction.BLOCK,
        reason="repeated_tool_output",
        repeated_output_count=3,
    )
    processor, backend_executor = _processor_with_guard(request_data, guard)

    response = await processor.process_request(MockRequestContext(), request_data)

    guard.evaluate_request.assert_awaited_once()
    backend_executor.execute.assert_not_called()
    assert response.status_code == 409
    assert "repeated_tool_output" in str(response.content)


@pytest.mark.asyncio
async def test_tool_progress_guard_allows_backend_dispatch_when_clear() -> None:
    request_data = _tool_followup_request()
    guard = AsyncMock()
    guard.evaluate_request.return_value = ToolProgressLoopDecision(
        action=ToolProgressLoopAction.ALLOW
    )
    processor, backend_executor = _processor_with_guard(request_data, guard)

    await processor.process_request(MockRequestContext(), request_data)

    guard.evaluate_request.assert_awaited_once()
    backend_executor.execute.assert_called_once()


@pytest.mark.asyncio
async def test_tool_progress_guard_uses_stable_resolved_session_id() -> None:
    request_data = _tool_followup_request()
    guard = AsyncMock()
    guard.evaluate_request.return_value = ToolProgressLoopDecision(
        action=ToolProgressLoopAction.ALLOW
    )
    processor, _ = _processor_with_guard(request_data, guard)

    await processor.process_request(
        MockRequestContext(session_id="request-scoped-session"), request_data
    )

    assert guard.evaluate_request.await_args.kwargs["session_id"] == "stable-session"
