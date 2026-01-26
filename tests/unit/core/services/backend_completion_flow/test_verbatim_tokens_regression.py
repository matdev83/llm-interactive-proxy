"""Regression tests for verbatim token calculation bug.

This module contains regression tests to ensure that the bug where verbatim tokens
were calculated as 0 when non-forwardable message filtering occurred is not reintroduced.

Bug: When non-forwardable message filtering was applied, canonical_request was modified
before being passed to calculate_and_record_usage as the "verbatim" request parameter.
Since the request had already been filtered, verbatim token calculation returned 0,
resulting in log messages like "Outbound tokens to gemini-oauth-plan.1/gemini-3-flash-preview: 123021 (verbatim: 0)".

Fix: Preserve original_canonical_request before non-forwardable filtering and use it
for verbatim token calculation, ensuring verbatim tokens reflect the request before filtering.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


@pytest.fixture
def mock_non_forwardable_enforcer():
    """Create a mock non-forwardable enforcer that filters messages."""
    mock = AsyncMock()

    # Simulate filtering: remove one message from the list
    async def filter_messages(session_id, messages, context=None):
        # Filter out messages with content "filtered message"
        filtered = [msg for msg in messages if msg.content != "filtered message"]
        filtered_count = len(messages) - len(filtered)
        return filtered, filtered_count

    mock.filter_messages = AsyncMock(side_effect=filter_messages)
    return mock


@pytest.fixture
def harness_with_filtering(
    mock_non_forwardable_enforcer: AsyncMock,
) -> BackendCompletionFlow:
    """Create BackendCompletionFlow harness with non-forwardable enforcer."""
    availability_checker = AsyncMock()
    availability_checker.check_backend_availability = AsyncMock(return_value=None)

    request_preparer = AsyncMock()
    request_preparer.prepare_request = AsyncMock(
        return_value=BackendTarget(
            backend="test-backend", model="test-model", uri_params={}
        )
    )

    # synchronize_request_with_target returns the request as-is
    def sync_request(request, target):
        return request

    request_preparer.synchronize_request_with_target = Mock(side_effect=sync_request)

    # prepare_backend_request returns the request as-is (no transformations for this test)
    async def prepare_backend(request, backend_type, session, uri_params):
        return request

    request_preparer.prepare_backend_request = AsyncMock(side_effect=prepare_backend)
    request_preparer.prepare_backend_kwargs = Mock(return_value={})

    session_resolver = AsyncMock()
    session_resolver.resolve_session = AsyncMock(
        return_value=(None, "test-session-123")
    )

    backend_invoker = AsyncMock()
    backend_mock = AsyncMock()
    backend_invoker.acquire_backend = AsyncMock(return_value=backend_mock)

    failover_executor = AsyncMock()
    failover_executor.check_complex_failover = AsyncMock(return_value=False)

    wire_capture_orchestrator = AsyncMock()
    wire_capture_orchestrator.prepare_wire_capture_context = AsyncMock(
        return_value=None
    )
    wire_capture_orchestrator.capture_wire_outbound = AsyncMock()

    usage_accounting = AsyncMock()
    usage_accounting.calculate_and_record_usage = AsyncMock(
        return_value=(10, "ctp", "ptb")
    )
    usage_accounting.handle_non_streaming_response = AsyncMock(
        return_value=ResponseEnvelope(content="test response")
    )

    exception_normalizer = Mock()

    stream_formatting_service = AsyncMock()
    connector_invoker = AsyncMock()
    connector_invoker.invoke = AsyncMock(
        return_value=ResponseEnvelope(content="test response")
    )

    service = BackendCompletionFlow(
        availability_checker=availability_checker,
        request_preparer=request_preparer,
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting_orchestrator=usage_accounting,
        exception_normalizer=exception_normalizer,
        stream_formatting_service=stream_formatting_service,
        connector_invoker=connector_invoker,
        resilience_coordinator=None,
        non_forwardable_enforcer=mock_non_forwardable_enforcer,
    )

    return service


@pytest.mark.asyncio
async def test_verbatim_tokens_calculated_from_original_request_before_filtering(
    harness_with_filtering: BackendCompletionFlow,
) -> None:
    """Regression test: verbatim tokens should be calculated from original request before filtering.

    Bug: canonical_request was modified by _enforce_non_forwardable_content before being
    passed to calculate_and_record_usage as the "verbatim" request parameter. This caused
    verbatim tokens to be calculated from an already-filtered request, resulting in 0 tokens.

    Fix: Preserve original_canonical_request before filtering and use it for verbatim token calculation.

    This test verifies that:
    1. calculate_and_record_usage receives domain_request with filtered messages (for outbound tokens)
    2. calculate_and_record_usage receives request with original messages (for verbatim tokens)
    3. Verbatim tokens are calculated correctly (non-zero) from the original request
    """
    # Setup: Create request with messages, one of which will be filtered
    original_messages = [
        ChatMessage(role="user", content="Hello, this is a test message"),
        ChatMessage(role="user", content="filtered message"),  # This will be filtered
        ChatMessage(role="assistant", content="Response"),
    ]

    request = CanonicalChatRequest(
        messages=original_messages,
        model="test-model",
    )

    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="test-session-123",
        request_id="req-456",
    )

    # Execute the completion flow
    await harness_with_filtering.call_completion(
        request=request,
        stream=False,
        allow_failover=False,
        context=context,
    )

    # Verify calculate_and_record_usage was called
    assert (
        harness_with_filtering._usage_accounting.calculate_and_record_usage.await_count
        == 1
    )

    # Get the call arguments - this is the key verification
    call_args = (
        harness_with_filtering._usage_accounting.calculate_and_record_usage.call_args
    )
    assert call_args is not None

    domain_request = call_args.kwargs["domain_request"]
    verbatim_request = call_args.kwargs["request"]

    # CRITICAL VERIFICATION: domain_request should have filtered messages (one message removed)
    assert len(domain_request.messages) == 2, (
        f"domain_request should have filtered messages (2 remaining), "
        f"but got {len(domain_request.messages)} messages"
    )
    assert all(
        msg.content != "filtered message" for msg in domain_request.messages
    ), "domain_request should not contain filtered message"

    # CRITICAL VERIFICATION: verbatim_request should have original messages (all messages present)
    # This is the bug fix - verbatim_request should NOT be filtered
    assert len(verbatim_request.messages) == 3, (
        f"verbatim_request should have original messages (3 total), "
        f"but got {len(verbatim_request.messages)} messages. "
        f"This indicates the bug: verbatim request was filtered when it shouldn't be."
    )
    assert any(
        msg.content == "filtered message" for msg in verbatim_request.messages
    ), "verbatim_request should contain the filtered message (original request before filtering)"

    # Verify the messages match what we expect
    verbatim_contents = [msg.content for msg in verbatim_request.messages]
    assert "Hello, this is a test message" in verbatim_contents
    assert "filtered message" in verbatim_contents
    assert "Response" in verbatim_contents


@pytest.mark.asyncio
async def test_verbatim_tokens_non_zero_when_messages_filtered(
    harness_with_filtering: BackendCompletionFlow,
) -> None:
    """Regression test: verbatim tokens should be non-zero even when messages are filtered.

    This test specifically verifies that verbatim tokens are calculated correctly
    and are non-zero when non-forwardable message filtering occurs.

    The bug would cause verbatim_request to have filtered messages, resulting in
    verbatim tokens being calculated as 0 (if all messages were filtered) or
    incorrectly low (if only some messages were filtered).
    """
    # Setup: Create request with messages that will be filtered
    original_messages = [
        ChatMessage(role="user", content="This message has content"),
        ChatMessage(role="user", content="filtered message"),  # Will be filtered
    ]

    request = CanonicalChatRequest(
        messages=original_messages,
        model="test-model",
    )

    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="test-session-123",
    )

    await harness_with_filtering.call_completion(
        request=request,
        stream=False,
        allow_failover=False,
        context=context,
    )

    # Verify calculate_and_record_usage was called
    call_args = (
        harness_with_filtering._usage_accounting.calculate_and_record_usage.call_args
    )
    assert call_args is not None

    domain_request = call_args.kwargs["domain_request"]
    verbatim_request = call_args.kwargs["request"]

    # Verify domain_request has filtered messages (1 message removed)
    assert (
        len(domain_request.messages) == 1
    ), "domain_request should have 1 message after filtering"
    assert all(msg.content != "filtered message" for msg in domain_request.messages)

    # CRITICAL: Verify verbatim_request has original messages (2 messages)
    # This is the key fix - verbatim_request should NOT be filtered
    assert len(verbatim_request.messages) == 2, (
        f"verbatim_request should have original 2 messages, "
        f"but got {len(verbatim_request.messages)}. "
        f"This indicates the bug: verbatim request was filtered."
    )

    # Verify verbatim tokens would be calculated from original request
    assert any(
        msg.content == "filtered message" for msg in verbatim_request.messages
    ), "verbatim_request should contain the filtered message (original request)"

    # The key assertion: verbatim_request should have MORE messages than domain_request
    # (because it's the original before filtering)
    assert len(verbatim_request.messages) > len(domain_request.messages), (
        "verbatim_request should have more messages than domain_request "
        "(original vs filtered)"
    )
