from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


def _build_flow_with_erroring_backend() -> BackendCompletionFlow:
    deps: dict[str, Any] = {
        "availability_checker": MagicMock(),
        "request_preparer": MagicMock(),
        "session_resolver": MagicMock(),
        "backend_invoker": MagicMock(),
        "failover_executor": MagicMock(),
        "wire_capture_orchestrator": MagicMock(),
        "usage_accounting_orchestrator": MagicMock(),
        "exception_normalizer": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "connector_invoker": MagicMock(),
    }

    deps["exception_normalizer"].normalize.side_effect = lambda exc, _backend: exc

    deps["request_preparer"].prepare_request = AsyncMock(
        return_value=MagicMock(
            backend="kimi-code",
            model="kimi/kimi-for-coding",
            uri_params={},
        )
    )
    deps["request_preparer"].synchronize_request_with_target.side_effect = (
        lambda req, _target: req
    )
    deps["failover_executor"].check_complex_failover = AsyncMock(return_value=False)
    deps["availability_checker"].check_backend_availability = AsyncMock()

    deps["session_resolver"].resolve_session = AsyncMock(
        return_value=(MagicMock(), "session-1")
    )
    deps["backend_invoker"].acquire_backend = AsyncMock(return_value=MagicMock())
    deps["request_preparer"].prepare_backend_request = AsyncMock(
        side_effect=lambda request, *_args, **_kwargs: request
    )
    deps["request_preparer"].prepare_backend_kwargs = MagicMock(return_value={})

    deps["wire_capture_orchestrator"].prepare_wire_capture_context = AsyncMock(
        return_value=None
    )
    deps["wire_capture_orchestrator"].capture_wire_outbound = AsyncMock()
    deps["wire_capture_orchestrator"].capture_inbound_response = AsyncMock()
    deps["wire_capture_orchestrator"].detect_key_name.return_value = "test-key"

    deps["usage_accounting_orchestrator"].calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    deps["usage_accounting_orchestrator"].handle_backend_error = AsyncMock()

    deps["connector_invoker"].invoke = AsyncMock(
        side_effect=HTTPException(
            status_code=413,
            detail={"message": "payload too large", "type": "openai_error"},
        )
    )

    return BackendCompletionFlow(**deps)


@pytest.mark.asyncio
async def test_streaming_call_returns_terminal_error_envelope_on_http_exception() -> (
    None
):
    flow = _build_flow_with_erroring_backend()

    request = ChatRequest(
        model="kimi-code:kimi/kimi-for-coding",
        messages=[ChatMessage(role="user", content="continue")],
    )

    result = await flow.call_completion(
        request=request,
        stream=True,
        allow_failover=False,
        context=None,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.status_code == 413

    assert result.content is not None
    chunks = [chunk async for chunk in result.content]
    assert len(chunks) == 1

    chunk_content = chunks[0].content
    assert isinstance(chunk_content, dict)
    choices = chunk_content.get("choices")
    assert isinstance(choices, list)
    assert choices
    first_choice = choices[0]
    assert isinstance(first_choice, dict)
    assert first_choice.get("finish_reason") == "error"

    error_content = chunk_content.get("error")
    assert isinstance(error_content, dict)
    assert error_content.get("status_code") == 413

    metadata = chunks[0].metadata
    assert isinstance(metadata, dict)
    assert metadata.get("finish_reason") == "error"

    error_payload = metadata.get("error")
    assert isinstance(error_payload, dict)
    assert error_payload.get("status_code") == 413
