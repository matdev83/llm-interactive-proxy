"""
Regression tests for CRITICAL streaming error response fallback bug.

ROOT CAUSE OF PRODUCTION ISSUE (2026-02-26):
When using streaming APIs, BackendCompletionFlowService returns StreamingResponseEnvelope
with error status codes (401, 500, etc.) instead of raising exceptions.

The original fallback logic ONLY caught exceptions, so streaming error envelopes
bypassed the fallback entirely and were sent directly to clients, causing:
1. Session interruptions
2. Stringified SSE markers like "data: [DONE]" visible to users
3. No automatic retry with original model

THE FIX:
Added detection in request_processor_service.py to convert error envelopes
to exceptions BEFORE returning, so the existing exception-based fallback logic
can catch and handle them.

This test file ensures this critical case is covered and will catch regressions.

Issue: OAuth rate limiting on replacement models causing universal session failures
Fixed in: Session 2026-02-26 (second iteration)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session
from src.core.services.request_processor_service import RequestProcessor


@pytest.fixture
def mock_replacement_service():
    """Mock replacement service with active gemini-oauth-auto replacement."""
    service = MagicMock()
    state = MagicMock()
    state.active = True
    state.replacement_backend = "gemini-oauth-auto"
    state.replacement_model = "gemini-3.1-pro-preview"
    state.original_backend = "openai"
    state.original_model = "gpt-4o"
    state.deactivate = MagicMock()
    service.get_state.return_value = state
    service.should_replace.return_value = False
    service.get_effective_backend_model.return_value = (
        "gemini-oauth-auto",
        "gemini-3.1-pro-preview",
    )
    return service


@pytest.fixture
def request_processor(mock_replacement_service):
    """Create RequestProcessor with minimal mocked dependencies."""
    processor = RequestProcessor(
        command_processor=MagicMock(),
        session_manager=AsyncMock(),
        backend_request_manager=AsyncMock(),
        response_manager=AsyncMock(),
        session_enricher=AsyncMock(),
        request_side_effects=AsyncMock(),
        command_handler=AsyncMock(),
        backend_preparer=AsyncMock(),
        transform_pipeline=AsyncMock(),
        backend_executor=AsyncMock(),
        app_state=MagicMock(),
        replacement_service=mock_replacement_service,
    )

    session = MagicMock(spec=Session)
    session.state.to_dict.return_value = {}

    # Create enricher mock that returns proper ChatRequest (not wrapped in coroutine)
    async def mock_enrich(ctx, req_data):
        return (session, req_data)

    # Create request side effects mock that returns request as-is
    async def mock_request_side_effects(ctx, sid, req_data):
        return req_data

    processor._session_enricher.enrich = AsyncMock(side_effect=mock_enrich)
    processor._request_side_effects.apply = AsyncMock(
        side_effect=mock_request_side_effects
    )
    processor._session_manager.resolve_session_id.return_value = "test-session"
    processor._session_manager.get_session.return_value = session
    processor._session_manager.apply_openai_codex_history_compaction_gate = AsyncMock()
    processor._command_handler.handle.return_value = ProcessedResult(
        command_executed=False, modified_messages=[], command_results=[]
    )

    # CRITICAL FIX: Use async functions, not lambdas, to avoid coroutine wrapping issues
    async def mock_transform(c, s, sid, req):
        return req

    async def mock_prepare(c, s, req, cmd, **_kwargs):
        return req

    processor._transform_pipeline.transform = AsyncMock(side_effect=mock_transform)
    processor._backend_preparer.prepare = AsyncMock(side_effect=mock_prepare)

    return processor


# ==============================================================================
# THE CRITICAL TEST: Streaming Error Envelope Fallback
# ==============================================================================


@pytest.mark.asyncio
async def test_streaming_401_error_envelope_triggers_fallback_not_client_error(
    request_processor,
    mock_replacement_service,
) -> None:
    """
    CRITICAL PRODUCTION BUG TEST.

    When backend_executor.execute() returns StreamingResponseEnvelope with
    status_code=401 (typical for OAuth rate limits), the fallback logic MUST
    catch it and retry with the original model.

    WITHOUT THIS FIX:
    - Error envelope flows to clients
    - Sessions interrupted
    - Stringified SSE visible: "data: [DONE]"

    WITH THIS FIX:
    - Error envelope converted to exception
    - Fallback logic catches it
    - Retry with original model
    - Session continues normally
    """
    context = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        client_host="127.0.0.1",
        original_request=None,
    )
    context.backend = "gemini-oauth-auto"
    context.effective_model = "gemini-3.1-pro-preview"

    request_data = ChatRequest(
        model="gemini-oauth-auto:gemini-3.1-pro-preview",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )

    execute_call_count = 0

    async def mock_execute(ctx, sess, sid, backend_req, req_data):
        nonlocal execute_call_count
        execute_call_count += 1

        if execute_call_count == 1:
            # FIRST CALL: Replacement model returns 401 error envelope (OAuth unavailable)
            # This simulates what BackendCompletionFlowService._build_terminal_error_stream_envelope() does
            async def error_iterator():
                yield b'data: {"id": "chatcmpl-error-123", "choices": [{"delta": {}, "finish_reason": "error"}], "error": {"type": "AuthenticationError", "message": "OAuth token unavailable"}}\n\n'
                yield b"data: [DONE]\n\n"

            return StreamingResponseEnvelope(
                content=error_iterator(),
                status_code=401,  # This is the key - error status!
                media_type="text/event-stream",
                metadata={
                    "error": {
                        "message": "OAuth token unavailable for gemini-oauth-auto"
                    }
                },
            )
        elif execute_call_count == 2:
            # SECOND CALL: Original model succeeds after fallback
            async def success_iterator():
                yield b'data: {"id": "chatcmpl-success", "choices": [{"delta": {"content": "Hello"}}]}\n\n'
                yield b"data: [DONE]\n\n"

            return StreamingResponseEnvelope(
                content=success_iterator(),
                status_code=200,
                media_type="text/event-stream",
            )
        else:
            raise AssertionError(f"Unexpected execute() call #{execute_call_count}")

    request_processor._backend_executor.execute = AsyncMock(side_effect=mock_execute)

    # Execute - should NOT raise, should fallback and succeed
    response = await request_processor.process_request(context, request_data)

    # CRITICAL ASSERTIONS
    assert (
        execute_call_count == 2
    ), "Must call execute() twice: once for replacement, once for fallback"

    # Replacement was deactivated (proves fallback was triggered)
    mock_replacement_service.get_state.return_value.deactivate.assert_called_once()

    # Response is the successful streaming envelope from fallback
    assert isinstance(response, StreamingResponseEnvelope)
    assert (
        response.status_code == 200
    ), "Fallback should return successful response, not error"


@pytest.mark.asyncio
async def test_non_streaming_exception_fallback_still_works(
    request_processor,
    mock_replacement_service,
) -> None:
    """
    Verify non-streaming exception-based fallback still works after fix.

    This ensures we didn't break the original exception-handling path.
    """
    context = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        client_host="127.0.0.1",
        original_request=None,
    )
    context.backend = "gemini-oauth-auto"
    context.effective_model = "gemini-3.1-pro-preview"

    request_data = ChatRequest(
        model="gemini-oauth-auto:gemini-3.1-pro-preview",
        messages=[ChatMessage(role="user", content="test")],
        stream=False,  # Non-streaming
    )

    execute_call_count = 0

    async def mock_execute(ctx, sess, sid, backend_req, req_data):
        nonlocal execute_call_count
        execute_call_count += 1

        if execute_call_count == 1:
            # Non-streaming: raise exception directly
            from src.core.common.exceptions import AuthenticationError

            raise AuthenticationError("OAuth token unavailable")
        else:
            return ResponseEnvelope(content={"message": "success"})

    request_processor._backend_executor.execute = AsyncMock(side_effect=mock_execute)

    response = await request_processor.process_request(context, request_data)

    assert execute_call_count == 2
    assert isinstance(response, ResponseEnvelope)
    mock_replacement_service.get_state.return_value.deactivate.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_200_response_no_fallback_triggered(
    request_processor,
    mock_replacement_service,
) -> None:
    """
    Successful streaming responses (status_code=200) should NOT trigger fallback.
    """
    context = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        client_host="127.0.0.1",
        original_request=None,
    )
    context.backend = "gemini-oauth-auto"
    context.effective_model = "gemini-3.1-pro-preview"

    request_data = ChatRequest(
        model="gemini-oauth-auto:gemini-3.1-pro-preview",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )

    async def success_stream():
        yield b'data: {"choices": [{"delta": {"content": "OK"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    request_processor._backend_executor.execute = AsyncMock(
        return_value=StreamingResponseEnvelope(
            content=success_stream(),
            status_code=200,
            media_type="text/event-stream",
        )
    )

    response = await request_processor.process_request(context, request_data)

    # Should NOT trigger fallback
    assert isinstance(response, StreamingResponseEnvelope)
    assert response.status_code == 200
    mock_replacement_service.get_state.return_value.deactivate.assert_not_called()

    # execute() should only be called once (no retry)
    assert request_processor._backend_executor.execute.call_count == 1
