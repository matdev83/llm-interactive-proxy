from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.di.services import get_or_build_service_provider
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.responses import ResponseEnvelope
from src.core.services.application_state_service import get_default_application_state
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer

from tests.unit.core.test_doubles import MockCommandProcessor, TestDataBuilder


@pytest.mark.asyncio
async def test_e2e_di_streaming_pipeline_sets_pending_and_next_call_tuned() -> None:
    # Build DI container
    provider = get_or_build_service_provider()

    # Configure provider AppConfig BEFORE resolving the normalizer
    prov_cfg = provider.get_required_service(AppConfig)
    prov_cfg.edit_precision.enabled = True
    prov_cfg.edit_precision.temperature = 0.12
    prov_cfg.edit_precision.override_top_p = True
    prov_cfg.edit_precision.min_top_p = 0.34
    prov_cfg.session.json_repair_enabled = False
    prov_cfg.session.tool_call_repair_enabled = False

    # Resolve the DI-wired normalizer now that config is set
    normalizer: StreamNormalizer = provider.get_required_service(StreamNormalizer)  # type: ignore[assignment]

    # Also publish to default app_state for request processor path
    app_state = get_default_application_state()
    app_state.set_setting("app_config", prov_cfg)

    session_id = "di-e2e-sess"

    # Create a stream that includes a failure marker; include id as fallback session key
    async def stream() -> AsyncGenerator[dict, None]:
        yield {
            "id": session_id,
            "choices": [{"delta": {"content": "partial..."}}],
        }
        yield {
            "id": session_id,
            "choices": [{"delta": {"content": "... diff_error ..."}}],
        }

    # Drive the DI-wired streaming pipeline (which includes MiddlewareApplicationProcessor)
    async for _ in normalizer.process_stream(stream(), output_format="objects"):
        pass

    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get(session_id, 0) >= 1

    # Now send the next request and assert tuning is applied
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session_manager.resolve_session_id.return_value = session_id
    session_manager.get_session.return_value = AsyncMock(id=session_id, agent=None)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Proceed")],
        stream=False,
    )
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_request_manager.prepare_backend_request.return_value = request
    backend_request_manager.process_backend_request.return_value = response
    response_manager.process_command_result.return_value = ResponseEnvelope(
        content={"ok": True}
    )

    rp = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        app_state=app_state,
    )
    await rp.process_request(
        __import__(
            "tests.unit.core.test_request_processor", fromlist=["MockRequestContext"]
        ).MockRequestContext(),
        request,
    )

    assert backend_request_manager.process_backend_request.called
    tuned = backend_request_manager.process_backend_request.call_args[0][0]
    assert tuned.temperature == pytest.approx(0.12)
    assert tuned.top_p == pytest.approx(0.34)
