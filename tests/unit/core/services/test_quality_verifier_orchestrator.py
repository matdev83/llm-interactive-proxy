from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.quality_verifier_orchestrator import (
    run_quality_verifier_decision,
)


def _request() -> ChatRequest:
    return ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
    )


def _context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-qv",
        session_id="sess-qv",
    )


class TestQualityVerifierOrchestrator:
    @pytest.mark.asyncio
    async def test_guard_blocks_verifier_call_before_dispatch(self) -> None:
        backend_service = MagicMock()
        backend_service.chat_completions = AsyncMock()
        backend_work_guard = MagicMock()
        backend_work_guard.ensure_session_active.side_effect = RuntimeError("cancelled")

        outcome = await run_quality_verifier_decision(
            original_request=_request(),
            assistant_text="assistant output",
            model_spec="openai:gpt-4o-mini",
            max_history=None,
            max_consecutive_failures=5,
            cooldown_seconds=30,
            ttft_timeout_seconds=0.2,
            backend_service=backend_service,
            request_context=_context(),
            cancellation_coordinator=None,
            notification_service=None,
            backend_work_guard=backend_work_guard,
        )

        assert outcome.kind == "verifier_failed"
        backend_service.chat_completions.assert_not_called()

    @pytest.mark.asyncio
    async def test_wraps_stream_with_guard_for_quality_verifier_purpose(self) -> None:
        async def _qv_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content="<status>NO_STEERING_NEEDED</status>",
                metadata={},
            )

        backend_service = MagicMock()
        backend_service.chat_completions = AsyncMock(
            return_value=StreamingResponseEnvelope(content=_qv_stream())
        )

        backend_work_guard = MagicMock()
        backend_work_guard.ensure_session_active.return_value = SessionKey(
            protocol="http",
            primary_id="req-qv",
        )

        def _pass_through(
            *, stream: AsyncIterator[Any], **kwargs: Any
        ) -> AsyncIterator[Any]:
            return stream

        backend_work_guard.wrap_stream_with_cancellation.side_effect = _pass_through

        outcome = await run_quality_verifier_decision(
            original_request=_request(),
            assistant_text="assistant output",
            model_spec="openai:gpt-4o-mini",
            max_history=None,
            max_consecutive_failures=5,
            cooldown_seconds=30,
            ttft_timeout_seconds=0.2,
            backend_service=backend_service,
            request_context=_context(),
            cancellation_coordinator=None,
            notification_service=None,
            backend_work_guard=backend_work_guard,
        )

        assert outcome.kind == "pass"
        backend_work_guard.wrap_stream_with_cancellation.assert_called_once()
        call_kwargs = backend_work_guard.wrap_stream_with_cancellation.call_args.kwargs
        assert call_kwargs["purpose"] == "quality_verifier"
