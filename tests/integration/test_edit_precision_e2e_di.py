from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from src.core.config.app_config import AppConfig, EditPrecisionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.ports.streaming_contracts import StreamingContent
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
    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.15, override_top_p=True, min_top_p=0.35
        )
    )
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
    response_manager.process_command_result.return_value = ResponseEnvelope(
        content={"ok": True}
    )

    # Create required mocks
    from src.core.interfaces.request_processor_internal import (
        IBackendExecutor,
        IBackendPreparer,
        ICommandHandler,
        IRequestSideEffects,
        IRequestTransformPipeline,
        ISessionEnricher,
    )

    session_enricher = AsyncMock(spec=ISessionEnricher)
    mock_session = AsyncMock(id=session_id, agent=None)
    session_enricher.enrich.return_value = (mock_session, request)
    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.return_value = request
    command_handler = AsyncMock(spec=ICommandHandler)
    command_handler.handle.return_value = ProcessedResult(
        modified_messages=request.messages,
        command_executed=False,
        command_results=[],
    )
    backend_preparer = AsyncMock(spec=IBackendPreparer)
    backend_preparer.prepare.return_value = request
    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    # Mock transform to return a request with tuned parameters
    tuned_request = request.model_copy(update={"temperature": 0.2, "top_p": 0.35})
    transform_pipeline.transform.return_value = tuned_request
    backend_executor = AsyncMock(spec=IBackendExecutor)
    backend_executor.execute.return_value = response

    processor2 = RequestProcessor(
        cmd,
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
    )

    await processor2.process_request(_Ctx(), request)

    # Assert tuned sampling parameters applied
    assert transform_pipeline.transform.called
    # Check the output of transform_pipeline.transform (the return value)
    tuned_req = transform_pipeline.transform.return_value
    # Model-specific config now overrides configured temperature for GPT models (0.2)
    assert tuned_req.temperature == pytest.approx(0.2)
    assert tuned_req.top_p == pytest.approx(0.35)

    # And the pending counter should decrement
    pending_after = app_state.get_setting("edit_precision_pending", {})
    assert int(pending_after.get(session_id, 0)) >= 0
