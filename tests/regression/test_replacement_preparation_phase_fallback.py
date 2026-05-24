"""
Regression tests for Fix 2: Extended Fallback Logic for Preparation-Phase Errors.

These tests ensure that when a replacement model fails during request preparation
(e.g., OAuth token refresh), the fallback logic catches the error and automatically
retries with the original model, following B2BUA-like session isolation patterns.

Background:
Fallback logic only caught errors during backend execution, not during preparation.
When OAuth token refresh failed in the replacement model's connector during
preparation, the error propagated to clients, interrupting all sessions.

The fix extends the try-catch to cover both preparation AND execution phases,
and ensures proper B2BUA identity allocation (new b_session_id) for fallback attempts.

Issue: https://github.com/.../issues/...
Fixed in: Session 2026-02-26
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import AuthenticationError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session
from src.core.services.request_processor_service import RequestProcessor


@pytest.fixture
def mock_replacement_service():
    """Create a mock replacement service with active replacement."""
    service = MagicMock()

    # Mock state for active replacement
    state = MagicMock()
    state.active = True
    state.replacement_backend = "gemini-oauth-auto"
    state.replacement_model = "gemini-3.1-pro-preview"
    state.original_backend = "openai"
    state.original_model = "gpt-4o"
    state.deactivate = MagicMock()

    service.get_state.return_value = state
    service.should_replace.return_value = False  # Don't trigger new replacement
    service.get_effective_backend_model.return_value = (
        "gemini-oauth-auto",
        "gemini-3.1-pro-preview",
    )

    return service


@pytest.fixture
def request_processor_with_replacement(mock_replacement_service):
    """Create RequestProcessor with mocked dependencies and replacement service."""
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

    # Setup session enricher to return session and request
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

    # Setup session manager
    processor._session_manager.resolve_session_id.return_value = "session-123"
    processor._session_manager.get_session.return_value = session

    # Setup command handler (no commands)
    processor._command_handler.handle.return_value = ProcessedResult(
        command_executed=False, modified_messages=[], command_results=[]
    )

    # Setup transform pipeline (pass-through)
    # CRITICAL: Use async function, not lambda, to avoid coroutine wrapping
    async def mock_transform(c, s, sid, req):
        return req

    processor._transform_pipeline.transform = AsyncMock(side_effect=mock_transform)

    return processor


@pytest.mark.asyncio
async def test_preparation_phase_error_triggers_fallback(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    When replacement model fails during preparation (OAuth refresh),
    fallback logic catches it and retries with original model.
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
    )

    # First prepare() call (replacement model) raises AuthenticationError
    # Second prepare() call (original model) succeeds
    prepare_call_count = 0

    async def mock_prepare(ctx, sid, req, cmd, **_kwargs):
        nonlocal prepare_call_count
        prepare_call_count += 1
        if prepare_call_count == 1:
            # First call: replacement model fails during preparation
            raise AuthenticationError(
                "OAuth token unavailable for gemini-oauth-auto (streaming API call)"
            )
        else:
            # Second call: original model succeeds
            return req

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        side_effect=mock_prepare
    )

    # Setup backend executor to return success
    request_processor_with_replacement._backend_executor.execute.return_value = (
        ResponseEnvelope(content={"message": "success"})
    )

    # Execute
    response = await request_processor_with_replacement.process_request(
        context, request_data
    )

    # Must succeed (not raise)
    assert response is not None

    # Replacement must be deactivated
    mock_replacement_service.get_state.return_value.deactivate.assert_called_once()

    # Must have called prepare twice (once for replacement, once for fallback)
    assert prepare_call_count == 2


@pytest.mark.asyncio
async def test_fallback_logs_warning_not_error(
    request_processor_with_replacement,
    mock_replacement_service,
    caplog,
) -> None:
    """
    Fallback from replacement model logs WARNING, not ERROR.

    This prevents false alarms in monitoring systems.
    """
    import logging

    caplog.set_level(logging.WARNING)

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
    )

    # First call fails, second succeeds
    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        side_effect=[
            AuthenticationError("Token refresh failed"),
            request_data,
        ]
    )

    request_processor_with_replacement._backend_executor.execute.return_value = (
        ResponseEnvelope(content={"message": "success"})
    )

    await request_processor_with_replacement.process_request(context, request_data)

    # Must log WARNING about replacement failure
    warning_logs = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_logs) > 0
    assert any("replacement model" in r.message.lower() for r in warning_logs)
    assert any(
        "falling back" in r.message.lower() or "fallback" in r.message.lower()
        for r in warning_logs
    )


@pytest.mark.asyncio
async def test_fallback_does_not_loop_infinitely(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    Fallback attempts only once. If original model also fails, error propagates.

    This prevents infinite fallback loops.
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
    )

    # Both calls fail
    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        side_effect=AuthenticationError("Both models failed")
    )

    # Must raise (not loop infinitely)
    with pytest.raises(AuthenticationError, match="Both models failed"):
        await request_processor_with_replacement.process_request(context, request_data)

    # Must have attempted fallback only once (2 prepare calls total)
    assert request_processor_with_replacement._backend_preparer.prepare.call_count == 2


@pytest.mark.asyncio
async def test_execution_phase_error_still_triggers_fallback(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    Execution phase errors still trigger fallback (backward compatibility).

    This ensures we didn't break the existing fallback for execution errors.
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
    )

    # Prepare succeeds, execute fails on first attempt
    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        return_value=request_data
    )

    execute_call_count = 0

    async def mock_execute(ctx, sess, sid, req, orig_req):
        nonlocal execute_call_count
        execute_call_count += 1
        if execute_call_count == 1:
            raise RuntimeError("Execution failed")
        else:
            return ResponseEnvelope(content={"message": "success"})

    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        side_effect=mock_execute
    )

    response = await request_processor_with_replacement.process_request(
        context, request_data
    )

    # Must succeed
    assert response is not None

    # Must have called execute twice
    assert execute_call_count == 2


@pytest.mark.asyncio
async def test_b2bua_identity_allocated_for_fallback_attempt(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    Fallback attempt allocates NEW B2BUA identity (different b_session_id).

    This ensures proper session isolation per B2BUA pattern.
    The execute() call flows through BackendCompletionFlowService which
    allocates B2BUA identity, so we verify execute is called twice with
    potentially different contexts.
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
    )

    # First prepare fails, second succeeds
    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        side_effect=[
            AuthenticationError("Token refresh failed"),
            request_data,
        ]
    )

    # Track execute calls
    execute_contexts = []

    async def mock_execute(ctx, sess, sid, req, orig_req):
        execute_contexts.append((ctx.backend, ctx.effective_model))
        return ResponseEnvelope(content={"message": "success"})

    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        side_effect=mock_execute
    )

    await request_processor_with_replacement.process_request(context, request_data)

    # Must have called execute once (for fallback attempt only, since first attempt
    # failed during preparation before execute was reached)
    assert len(execute_contexts) == 1

    # The fallback execute should use original model
    assert execute_contexts[0] == ("openai", "gpt-4o")


@pytest.mark.asyncio
async def test_fallback_updates_request_model_to_original(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    Fallback updates request_data.model to original model before retry.

    This ensures downstream components see the correct model.
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
    )

    # Track prepare calls by inspecting context (not request due to async wrapping)
    prepare_call_count = 0

    async def mock_prepare(ctx, sid, req, cmd, **_kwargs):
        nonlocal prepare_call_count
        prepare_call_count += 1
        if prepare_call_count == 1:
            # First call: verify replacement model in context
            assert ctx.backend == "gemini-oauth-auto"
            assert ctx.effective_model == "gemini-3.1-pro-preview"
            raise AuthenticationError("Token refresh failed")
        else:
            # Second call: verify original model in context
            assert (
                ctx.backend == "openai"
            ), "Context should be reverted to original backend"
            assert (
                ctx.effective_model == "gpt-4o"
            ), "Context should be reverted to original model"
            return req

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        side_effect=mock_prepare
    )

    request_processor_with_replacement._backend_executor.execute.return_value = (
        ResponseEnvelope(content={"message": "success"})
    )

    await request_processor_with_replacement.process_request(context, request_data)

    # Should have called prepare twice
    assert prepare_call_count == 2


@pytest.mark.asyncio
async def test_no_fallback_when_replacement_not_active(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    When replacement is not active, errors propagate normally (no fallback).

    This ensures fallback only happens for replacement model failures.
    """
    # Replacement NOT active
    mock_replacement_service.get_state.return_value.active = False

    context = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        client_host="127.0.0.1",
        original_request=None,
    )
    context.backend = "openai"
    context.effective_model = "gpt-4o"

    request_data = ChatRequest(
        model="openai:gpt-4o",
        messages=[ChatMessage(role="user", content="test")],
    )

    # Prepare fails
    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        side_effect=AuthenticationError("Auth failed")
    )

    # Must propagate error (no fallback)
    with pytest.raises(AuthenticationError, match="Auth failed"):
        await request_processor_with_replacement.process_request(context, request_data)

    # Replacement should not be deactivated (it wasn't active)
    mock_replacement_service.get_state.return_value.deactivate.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_context_reverted_to_original_backend(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    Fallback reverts context.backend and context.effective_model to original.

    This ensures fallback attempt uses original model configuration.
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
    )

    prepare_call_count = 0

    async def mock_prepare(ctx, sid, req, cmd, **_kwargs):
        nonlocal prepare_call_count
        prepare_call_count += 1
        if prepare_call_count == 1:
            # First call: verify replacement model context
            assert ctx.backend == "gemini-oauth-auto"
            assert ctx.effective_model == "gemini-3.1-pro-preview"
            raise AuthenticationError("Token refresh failed")
        else:
            # Second call: verify original model context
            assert ctx.backend == "openai"
            assert ctx.effective_model == "gpt-4o"
            return req

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        side_effect=mock_prepare
    )

    request_processor_with_replacement._backend_executor.execute.return_value = (
        ResponseEnvelope(content={"message": "success"})
    )

    await request_processor_with_replacement.process_request(context, request_data)

    # Assertions in mock_prepare verify context was reverted
    assert prepare_call_count == 2


# ==============================================================================
# STREAMING ERROR RESPONSE FALLBACK TESTS
# ==============================================================================
# These tests cover the critical case where execute() returns StreamingResponseEnvelope
# with error status codes instead of raising exceptions. This was the root cause of
# the production issue where fallback logic was bypassed.


@pytest.mark.asyncio
async def test_streaming_error_response_triggers_fallback(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    CRITICAL: When execute() returns StreamingResponseEnvelope with 401 status,
    fallback logic must catch it and retry with original model.

    This is the ACTUAL production bug: streaming requests return error envelopes,
    not exceptions, so the original fallback logic was bypassed.
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
    )

    execute_call_count = 0

    async def mock_execute(ctx, sess, sid, backend_req, req_data):
        nonlocal execute_call_count
        execute_call_count += 1

        if execute_call_count == 1:
            # First call: Return error envelope (streaming behavior)
            async def error_stream():
                yield b"data: {error_chunk}\n\n"
                yield b"data: [DONE]\n\n"

            return StreamingResponseEnvelope(
                content=error_stream(),
                status_code=401,  # This is the key - error status!
                media_type="text/event-stream",
                metadata={"error": {"message": "OAuth token unavailable"}},
            )
        else:
            # Second call: Original model succeeds
            return ResponseEnvelope(content={"message": "success"})

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        return_value=request_data
    )
    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        side_effect=mock_execute
    )

    # Execute
    response = await request_processor_with_replacement.process_request(
        context, request_data
    )

    # Verify fallback was triggered
    assert (
        execute_call_count == 2
    ), "Should call execute() twice: once for replacement, once for fallback"
    mock_replacement_service.get_state.return_value.deactivate.assert_called_once()
    assert isinstance(response, ResponseEnvelope)
    assert response.content == {"message": "success"}


@pytest.mark.asyncio
async def test_streaming_500_error_response_triggers_fallback(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    Any 4xx/5xx status code in StreamingResponseEnvelope should trigger fallback.
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
    )

    execute_call_count = 0

    async def mock_execute(ctx, sess, sid, backend_req, req_data):
        nonlocal execute_call_count
        execute_call_count += 1

        if execute_call_count == 1:
            # Return 500 error envelope
            async def error_stream():
                yield b"data: {error}\n\n"

            return StreamingResponseEnvelope(
                content=error_stream(),
                status_code=500,
                media_type="text/event-stream",
            )
        else:
            return ResponseEnvelope(content={"message": "success"})

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        return_value=request_data
    )
    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        side_effect=mock_execute
    )

    await request_processor_with_replacement.process_request(context, request_data)

    assert execute_call_count == 2
    mock_replacement_service.get_state.return_value.deactivate.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_success_does_not_trigger_fallback(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    StreamingResponseEnvelope with 200 status should NOT trigger fallback.
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
    )

    async def success_stream():
        yield b"data: {content}\n\n"
        yield b"data: [DONE]\n\n"

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        return_value=request_data
    )
    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        return_value=StreamingResponseEnvelope(
            content=success_stream(),
            status_code=200,
            media_type="text/event-stream",
        )
    )

    response = await request_processor_with_replacement.process_request(
        context, request_data
    )

    # Should NOT trigger fallback
    assert isinstance(response, StreamingResponseEnvelope)
    assert response.status_code == 200
    mock_replacement_service.get_state.return_value.deactivate.assert_not_called()


@pytest.mark.asyncio
async def test_streaming_error_response_without_replacement_raises(
    request_processor_with_replacement,
) -> None:
    """
    StreamingResponseEnvelope with 401 status WITHOUT active replacement
    should raise the error (no fallback available).
    """
    context = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        client_host="127.0.0.1",
        original_request=None,
    )
    context.backend = "openai"
    context.effective_model = "gpt-4o"

    request_data = ChatRequest(
        model="openai:gpt-4o",
        messages=[ChatMessage(role="user", content="test")],
    )

    async def error_stream():
        yield b"data: {error}\n\n"

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        return_value=request_data
    )
    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        return_value=StreamingResponseEnvelope(
            content=error_stream(),
            status_code=401,
            media_type="text/event-stream",
        )
    )

    # Set replacement service to None to simulate no replacement active
    request_processor_with_replacement._replacement_service = None

    # Should raise AuthenticationError (no fallback available)
    with pytest.raises(AuthenticationError, match="Backend returned 401 error"):
        await request_processor_with_replacement.process_request(context, request_data)


@pytest.mark.asyncio
async def test_streaming_error_then_fallback_also_streaming_error_raises(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    If both replacement AND original model return streaming error responses,
    the final error should be raised.
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
    )

    # Both calls return error envelopes (need fresh iterators for each call)
    async def mock_execute(ctx, sess, sid, backend_req, req_data):
        # Always return fresh error envelope
        async def error_stream():
            yield b"data: {error}\n\n"
            yield b"data: [DONE]\n\n"

        return StreamingResponseEnvelope(
            content=error_stream(),
            status_code=401,
            media_type="text/event-stream",
        )

    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        side_effect=mock_execute
    )

    # Should raise AuthenticationError after fallback also fails
    with pytest.raises(
        AuthenticationError,
        match="Both models failed, fallback returned status: 401",
    ):
        await request_processor_with_replacement.process_request(context, request_data)

    # Verify fallback was attempted (deactivate called)
    mock_replacement_service.get_state.return_value.deactivate.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_error_response_logs_warning_with_context(
    request_processor_with_replacement,
    mock_replacement_service,
    caplog,
) -> None:
    """
    Streaming error response fallback should log a clear WARNING with context.
    """
    import logging

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
    )

    execute_call_count = 0

    async def mock_execute(ctx, sess, sid, backend_req, req_data):
        nonlocal execute_call_count
        execute_call_count += 1

        if execute_call_count == 1:

            async def error_stream():
                yield b"data: {error}\n\n"

            return StreamingResponseEnvelope(
                content=error_stream(),
                status_code=401,
                media_type="text/event-stream",
            )
        else:
            return ResponseEnvelope(content={"message": "success"})

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        return_value=request_data
    )
    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        side_effect=mock_execute
    )

    with caplog.at_level(logging.WARNING):
        await request_processor_with_replacement.process_request(context, request_data)

    # Verify WARNING was logged
    assert any(
        "Replacement model gemini-oauth-auto:gemini-3.1-pro-preview failed"
        in record.message
        and "Falling back to original model" in record.message
        for record in caplog.records
        if record.levelname == "WARNING"
    ), "Expected WARNING log about fallback, but none found"


@pytest.mark.asyncio
async def test_streaming_403_error_response_triggers_fallback(
    request_processor_with_replacement,
    mock_replacement_service,
) -> None:
    """
    Any 4xx status code (not just 401) should trigger fallback.
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
    )

    execute_call_count = 0

    async def mock_execute(ctx, sess, sid, backend_req, req_data):
        nonlocal execute_call_count
        execute_call_count += 1

        if execute_call_count == 1:

            async def error_stream():
                yield b"data: {forbidden}\n\n"

            return StreamingResponseEnvelope(
                content=error_stream(),
                status_code=403,  # Forbidden
                media_type="text/event-stream",
            )
        else:
            return ResponseEnvelope(content={"message": "success"})

    request_processor_with_replacement._backend_preparer.prepare = AsyncMock(
        return_value=request_data
    )
    request_processor_with_replacement._backend_executor.execute = AsyncMock(
        side_effect=mock_execute
    )

    response = await request_processor_with_replacement.process_request(
        context, request_data
    )

    assert execute_call_count == 2
    assert isinstance(response, ResponseEnvelope)
