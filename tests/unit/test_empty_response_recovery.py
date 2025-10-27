from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest, ChatResponse
from src.core.domain.request_context import (
    ProcessingContext,
    RequestContext,
    RequestCookies,
    RequestHeaders,
)
from src.core.services.empty_response_recovery import EmptyResponseRecovery


@pytest.mark.asyncio
async def test_retry_on_empty_response() -> None:
    recovery = EmptyResponseRecovery()

    context = RequestContext(
        headers=RequestHeaders(raw={}),
        cookies=RequestCookies(raw={}),
        state=None,
        app_state=None,
        session_id="test-session",
        processing_context=ProcessingContext(values={}),
    )

    request = ChatRequest(
        model="test",
        messages=[ChatMessage(role="user", content="hi")],
    )

    response = ChatResponse(id="123", created=0, model="test", choices=[])

    result = await recovery.retry_if_needed(context, request, response)

    assert result is None
    assert context.session_id == "test-session"
