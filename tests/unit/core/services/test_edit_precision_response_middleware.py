from __future__ import annotations

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.application_state_service import (
    ApplicationStateService,
    get_default_application_state,
    set_default_application_state,
)
from src.core.services.edit_precision_response_middleware import (
    EditPrecisionResponseMiddleware,
)
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)


@pytest.fixture(autouse=True)
def _reset_app_state() -> None:
    """Ensure a clean default application state per test."""
    set_default_application_state(ApplicationStateService())


@pytest.mark.asyncio
async def test_response_middleware_sets_pending_on_non_streaming_match() -> None:
    mw = EditPrecisionResponseMiddleware()

    session_id = "sess-123"
    resp = ProcessedResponse(content="Something something diff_error occurred")

    out = await mw.process(resp, session_id, context={"response_type": "non_streaming"})
    assert isinstance(out, ProcessedResponse)

    app_state = get_default_application_state()
    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get(session_id, 0) >= 1


@pytest.mark.asyncio
async def test_streaming_processor_applies_middleware_and_sets_pending() -> None:
    # Build processor with our middleware
    mw = EditPrecisionResponseMiddleware()
    processor = MiddlewareApplicationProcessor([mw])

    # Simulate a streaming chunk that includes a trigger fragment
    sc = StreamingContent(
        content="... hunk failed to apply ...",
        metadata={"session_id": "stream-abc"},
    )

    out = await processor.process(sc)
    assert isinstance(out, StreamingContent)
    assert out.content == sc.content  # middleware does not alter content

    app_state = get_default_application_state()
    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get("stream-abc", 0) >= 1
