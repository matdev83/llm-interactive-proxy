from __future__ import annotations

import json

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.application_state_service import (
    ApplicationStateService,
)
from src.core.services.edit_precision_response_middleware import (
    EditPrecisionResponseMiddleware,
)
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)


@pytest.fixture
def app_state() -> ApplicationStateService:
    """Ensure a clean application state per test."""
    return ApplicationStateService()


@pytest.mark.asyncio
async def test_response_middleware_sets_pending_on_non_streaming_match(
    app_state: ApplicationStateService,
) -> None:
    mw = EditPrecisionResponseMiddleware(app_state)

    session_id = "sess-123"
    resp = ProcessedResponse(content="Something something diff_error occurred")

    out = await mw.process(resp, session_id, context={"response_type": "non_streaming"})
    assert isinstance(out, ProcessedResponse)

    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get(session_id, 0) >= 1


@pytest.mark.asyncio
async def test_streaming_processor_applies_middleware_and_sets_pending(
    app_state: ApplicationStateService,
) -> None:
    # Build processor with our middleware
    mw = EditPrecisionResponseMiddleware(app_state)
    processor = MiddlewareApplicationProcessor([mw], app_state=app_state)

    # Simulate a streaming chunk that includes a trigger fragment
    sc = StreamingContent(
        content="... hunk failed to apply ...",
        metadata={"session_id": "stream-abc"},
    )

    out = await processor.process(sc)
    assert isinstance(out, StreamingContent)
    assert out.content == sc.content  # middleware does not alter content

    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get("stream-abc", 0) >= 1
    active_flags = app_state.get_setting("edit_precision_hybrid_reasoning_active", {})
    assert "stream-abc" in active_flags


@pytest.mark.asyncio
async def test_streaming_duplicate_without_stream_id_only_flags_once(
    app_state: ApplicationStateService,
) -> None:
    """Test that chunks without explicit stream_id use session_id as stream_id.

    When no stream_id is provided, the middleware uses session_id as the stream
    identifier. All chunks with the same session_id are considered part of the
    same stream and should only trigger once, regardless of clearing the active flag.
    """
    mw = EditPrecisionResponseMiddleware(app_state)
    processor = MiddlewareApplicationProcessor([mw], app_state=app_state)

    session_id = "stream-no-id"
    first_chunk = StreamingContent(
        content="... diff_error ...",
        metadata={"session_id": session_id},
    )
    second_chunk = StreamingContent(
        content="... diff_error again ...",
        metadata={"session_id": session_id},
    )

    await processor.process(first_chunk)
    await processor.process(second_chunk)

    pending = app_state.get_setting("edit_precision_pending", {})
    assert pending.get(session_id, 0) == 1

    # Clear active flag to simulate the RequestProcessor consuming it
    active_flags = app_state.get_setting("edit_precision_hybrid_reasoning_active", {})
    assert session_id in active_flags
    active_flags.pop(session_id, None)
    app_state.set_setting("edit_precision_hybrid_reasoning_active", active_flags)

    # Third chunk with same session_id is still part of the same "stream"
    # (since session_id is used as stream_id when no explicit stream_id is provided)
    # so it should NOT re-trigger, even after clearing the active flag.
    third_chunk = StreamingContent(
        content="... diff_error final ...",
        metadata={"session_id": session_id},
    )
    await processor.process(third_chunk)

    # Pending count should still be 1 because all chunks are part of the same stream
    pending_after = app_state.get_setting("edit_precision_pending", {})
    assert pending_after.get(session_id, 0) == 1


@pytest.mark.asyncio
async def test_streaming_processor_only_increments_once_per_stream(
    app_state: ApplicationStateService,
) -> None:
    mw = EditPrecisionResponseMiddleware(app_state)
    processor = MiddlewareApplicationProcessor([mw], app_state=app_state)

    session_id = "stream-dup"
    first_chunk = StreamingContent(
        content="... diff_error ...",
        metadata={"session_id": session_id, "stream_id": "stream-1"},
    )
    second_chunk = StreamingContent(
        content="... diff_error again ...",
        metadata={"session_id": session_id, "stream_id": "stream-1"},
    )

    await processor.process(first_chunk)
    await processor.process(second_chunk)

    pending_once = app_state.get_setting("edit_precision_pending", {})
    assert pending_once.get(session_id, 0) == 1
    active_flags = app_state.get_setting("edit_precision_hybrid_reasoning_active", {})
    assert session_id in active_flags

    # Simulate the RequestProcessor consuming the flag between streams
    active_flags.pop(session_id, None)
    app_state.set_setting("edit_precision_hybrid_reasoning_active", active_flags)

    third_chunk = StreamingContent(
        content="... diff_error final ...",
        metadata={"session_id": session_id, "stream_id": "stream-2"},
    )
    await processor.process(third_chunk)

    pending_twice = app_state.get_setting("edit_precision_pending", {})
    assert pending_twice.get(session_id, 0) == 2


@pytest.mark.asyncio
async def test_metadata_patch_file_error_sets_pending(
    app_state: ApplicationStateService,
) -> None:
    mw = EditPrecisionResponseMiddleware(app_state)

    session_id = "sess-patch-metadata"
    arguments = json.dumps(
        {
            "tool_name": "patch_file",
            "tool_arguments": {"status": "error", "error_type": "diff_error"},
        }
    )
    resp = ProcessedResponse(
        content="",
        metadata={
            "tool_calls": [
                {
                    "function": {
                        "name": "__proxy_use_mcp_tool",
                        "arguments": arguments,
                    },
                    "result": {"success": False, "error": "diff_error"},
                }
            ]
        },
    )

    await mw.process(resp, session_id, context={"response_type": "non_streaming"})

    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get(session_id, 0) >= 1


@pytest.mark.asyncio
async def test_metadata_turbo_edit_file_error_sets_pending(
    app_state: ApplicationStateService,
) -> None:
    mw = EditPrecisionResponseMiddleware(app_state)

    session_id = "sess-turbo"
    resp = ProcessedResponse(
        content="",
        metadata={
            "tool_calls": [
                {
                    "function": {
                        "name": "turbo_edit_file",
                        "arguments": json.dumps(
                            {"diff": "---", "status": "failed", "error": "hunk failed"}
                        ),
                    },
                    "status": "failed",
                }
            ]
        },
    )

    await mw.process(resp, session_id, context={"response_type": "non_streaming"})

    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get(session_id, 0) >= 1
