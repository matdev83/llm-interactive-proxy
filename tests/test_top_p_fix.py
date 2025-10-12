from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.request_processor_service import RequestProcessor


@pytest.mark.asyncio
async def test_top_p_fix_with_actual_request() -> None:
    """Ensure top_p stays on the main request and is not copied into extra_body."""

    # Backend processor wired with a fake backend service so we exercise the real code path
    backend_service = AsyncMock()
    backend_service.call_completion = AsyncMock(
        return_value=ResponseEnvelope(
            content=None, headers={}, status_code=200, media_type="application/json"
        )
    )
    session_service = AsyncMock()
    test_session = Session(session_id="test_session")
    session_service.get_session.return_value = test_session
    app_state = MagicMock()
    app_state.get_failover_routes.return_value = None

    backend_processor = BackendProcessor(backend_service, session_service, app_state)
    response_processor = AsyncMock()
    backend_request_manager = BackendRequestManager(
        backend_processor=backend_processor,
        response_processor=response_processor,
    )

    # Command processor returns no-op processing result so backend path is taken
    command_processor = AsyncMock()
    command_processor.process_messages.return_value = ProcessedResult(
        modified_messages=[], command_executed=False, command_results=[]
    )

    # Session manager resolves and returns the session we prepared above
    session_manager = AsyncMock()
    session_manager.resolve_session_id.return_value = "test_session"
    session_manager.get_session.return_value = test_session
    session_manager.update_session_agent.return_value = test_session
    session_manager.record_command_in_session.return_value = None
    session_manager.update_session_history.return_value = None

    response_manager = AsyncMock()

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
    )

    request_data = ChatRequest(
        model="anthropic:claude-3-haiku-20240229",
        max_tokens=128,
        top_p=0.9,
        messages=[ChatMessage(role="user", content="Hello")],
        extra_body={"metadata": {"foo": "bar"}},
    )

    context = MagicMock()
    context.session_id = "test_session"

    await processor.process_request(context, request_data)

    await_count = backend_service.call_completion.await_count
    assert await_count == 1
    call_args = backend_service.call_completion.await_args_list[0]
    forwarded_request = call_args.kwargs["request"]

    # Ensure we exercised the real backend path and received a ChatRequest instance
    assert isinstance(forwarded_request, ChatRequest)
    assert forwarded_request.top_p == 0.9

    extra_body: dict[str, Any] = forwarded_request.extra_body or {}
    assert extra_body.get("session_id") == "test_session"
    assert extra_body.get("metadata") == {"foo": "bar"}

    # The regression we guard against: top_p must not leak into extra_body
    assert "top_p" not in extra_body
