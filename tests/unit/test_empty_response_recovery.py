from __future__ import annotations

import pytest
from src.core.config.app_config import AppConfig, EmptyResponseConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import (
    ProcessingContext,
    RequestContext,
    RequestCookies,
    RequestHeaders,
)
from src.core.services.empty_response_recovery import EmptyResponseRecovery


@pytest.mark.asyncio
async def test_retry_if_needed_returns_processed_response() -> None:
    recovery = EmptyResponseRecovery(
        AppConfig(empty_response=EmptyResponseConfig(enabled=True, max_retries=1))
    )

    context = RequestContext(
        headers=RequestHeaders({}),
        cookies=RequestCookies({}),
        state=None,
        app_state=None,
        session_id="session-xyz",
        processing_context=ProcessingContext(values={}),
    )

    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Empty content triggers steering
    response = {"content": ""}

    result = await recovery.retry_if_needed(context, request, response)

    assert result is None
