from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.edit_precision_response_middleware import (
    EditPrecisionResponseMiddleware,
)
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)

from tests.unit.core.test_doubles import MockCommandProcessor, TestDataBuilder


class _Ctx(RequestContext):
    def __init__(self) -> None:
        super().__init__(headers={}, cookies={}, state=None, app_state=None)


@pytest.mark.asyncio
async def test_e2e_stream_detection_flags_next_call_and_tunes_request() -> None:
    """Test end-to-end edit precision middleware using proper DI."""
    # Create app state service using proper DI approach
    app_state = ApplicationStateService()

    # Configure edit-precision settings
    app_config = AppConfig()
    app_config.edit_precision.enabled = True
    app_config.edit_precision.temperature = 0.15
    app_config.edit_precision.override_top_p = True
    app_config.edit_precision.min_top_p = 0.35
    app_state.set_setting("app_config", app_config)

    session_id = "e2e-sess"

    # Phase 1: simulate streaming response with an edit-failure marker
    mw = EditPrecisionResponseMiddleware(app_state)
    processor = MiddlewareApplicationProcessor([mw], app_state=app_state)

    sc = StreamingContent(
        content="... diff_error encountered ...", metadata={"session_id": session_id}
    )
    out = await processor.process(sc)
    assert out.content == sc.content

    # Pending flag should be set for the session
    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get(session_id, 0) >= 1

    # Phase 2: next request should be tuned even without prompt triggers
    cmd = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Wire simple session behavior
    session_manager.resolve_session_id.return_value = session_id
    session_manager.get_session.return_value = AsyncMock(id=session_id, agent=None)

    # Request without any failure phrase
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Do the next step")],
        stream=False,
    )

    # No command modifications
    cmd.add_result(
        ProcessedResult(
            modified_messages=request.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Backend stubs
    response = TestDataBuilder.create_chat_response("OK")
    backend_request_manager.prepare_backend_request.return_value = request
    backend_request_manager.process_backend_request.return_value = response
    response_manager.process_command_result.return_value = ResponseEnvelope(
        content={"ok": True}
    )

    processor2 = RequestProcessor(
        cmd,
        session_manager,
        backend_request_manager,
        response_manager,
        app_state=app_state,
    )

    await processor2.process_request(_Ctx(), request)

    # Assert tuned sampling parameters applied
    assert backend_request_manager.process_backend_request.called
    tuned_req = backend_request_manager.process_backend_request.call_args[0][0]
    assert tuned_req.temperature == pytest.approx(0.15)
    assert tuned_req.top_p == pytest.approx(0.35)

    # And the pending counter should decrement
    pending_after = app_state.get_setting("edit_precision_pending", {})
    assert int(pending_after.get(session_id, 0)) >= 0
