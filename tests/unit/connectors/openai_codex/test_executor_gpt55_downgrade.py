"""ResponseExecutor: gpt-5.5 free-plan reactive downgrade (HTTP 400 from upstream)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import stamina
from fastapi import HTTPException
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexPayload,
    CodexRequestContext,
    ProcessedMessage,
)
from src.connectors.openai_codex.executor import ResponseExecutor
from src.connectors.openai_codex.gpt55_account_compatibility import (
    Gpt55FreePlanDowngradeConfig,
)
from src.connectors.openai_codex.interfaces import ICredentialManager
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

_UPSTREAM_400 = {
    "detail": (
        "The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account."
    )
}


def _context() -> CodexRequestContext:
    request = CanonicalChatRequest(
        model="gpt-5.5",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
    )
    return CodexRequestContext(
        request=request,
        processed_messages=[
            ProcessedMessage(role="user", content="hello", tool_calls=None)
        ],
        effective_model="gpt-5.5",
        capabilities=CodexClientCapabilities(),
        session_id="gpt55-downgrade-session",
    )


def _payload() -> CodexPayload:
    return CodexPayload(
        model="gpt-5.5",
        input=[],
        tools=[],
        tool_choice="auto",
        parallel_tool_calls=False,
        store=False,
        stream=True,
        include=[],
        prompt_cache_key="gpt55-k",
    )


def _build_connector_mock() -> MagicMock:
    connector = MagicMock()
    connector.client = MagicMock()
    connector.translation_service = MagicMock()
    connector.get_headers = MagicMock(
        return_value={"Authorization": "Bearer test-token"}
    )
    connector.update_quota_headers = MagicMock()
    return connector


def _build_credential_manager_mock() -> MagicMock:
    manager = MagicMock(spec=ICredentialManager)
    manager.refresh_access_token = AsyncMock(return_value=True)
    manager.get_access_token = MagicMock(return_value="fresh-token")
    manager.get_codex_plan_type_hint = MagicMock(return_value=None)
    return manager


@pytest.mark.asyncio
async def test_reactive_downgrade_retries_with_gpt54() -> None:
    connector = _build_connector_mock()
    credential_manager = _build_credential_manager_mock()
    # Explicit: unconfigured MagicMock is truthy and can confuse proactive heuristics.
    credential_manager.get_codex_plan_type_hint = MagicMock(return_value=None)
    context = _context()
    payload = _payload()

    async def success_iterator() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content={"choices": [{"delta": {"content": "ok"}}]})

    stream_handle = MagicMock()
    stream_handle.headers = {"x-request-id": "req-1"}
    stream_handle.cancel_callback = AsyncMock()
    stream_handle.iterator = success_iterator()

    transport = MagicMock()
    transport.initiate_streaming_request = AsyncMock(
        side_effect=[
            HTTPException(status_code=400, detail=_UPSTREAM_400),
            stream_handle,
        ]
    )
    # Proactive is covered in test_proactive_downgrade_when_plan_hint_free; disable here
    # so the first upstream attempt is guaranteed to use gpt-5.5.
    g55 = Gpt55FreePlanDowngradeConfig(
        enabled=True,
        proactive_enabled=False,
        reactive_enabled=True,
    )
    executor = ResponseExecutor(
        connector,
        credential_manager,
        max_retries=2,
        retry_backoff_seconds=(0.1, 0.2),
        transport=transport,
        gpt55_free_plan_downgrade=g55,
    )
    with stamina.set_testing(True, attempts=3, cap=True):
        result = await executor.execute(payload, context)
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.content is not None
        chunks = [c async for c in result.content]

    assert len(chunks) == 1
    assert transport.initiate_streaming_request.await_count == 2
    first_call = transport.initiate_streaming_request.call_args_list[0]
    second_call = transport.initiate_streaming_request.call_args_list[1]
    assert first_call.args[1].get("model") == "gpt-5.5"
    assert second_call.args[1].get("model") == "gpt-5.4"


@pytest.mark.asyncio
async def test_unrelated_400_not_recovered() -> None:
    connector = _build_connector_mock()
    credential_manager = _build_credential_manager_mock()
    credential_manager.get_codex_plan_type_hint = MagicMock(return_value=None)
    context = _context()
    payload = _payload()
    transport = MagicMock()
    transport.initiate_streaming_request = AsyncMock(
        side_effect=HTTPException(
            status_code=400, detail={"detail": "unrelated client error"}
        )
    )
    g55 = Gpt55FreePlanDowngradeConfig()
    executor = ResponseExecutor(
        connector,
        credential_manager,
        max_retries=1,
        retry_backoff_seconds=(0.1,),
        transport=transport,
        gpt55_free_plan_downgrade=g55,
    )
    with (
        stamina.set_testing(True, attempts=3, cap=True),
        pytest.raises(HTTPException) as exc,
    ):
        result = await executor.execute(payload, context)
        assert result.content is not None
        async for _ in result.content:
            pass
    assert exc.value.status_code == 400
    assert transport.initiate_streaming_request.await_count == 1


@pytest.mark.asyncio
async def test_proactive_downgrade_when_plan_hint_free() -> None:
    connector = _build_connector_mock()
    credential_manager = _build_credential_manager_mock()
    credential_manager.get_codex_plan_type_hint = MagicMock(return_value="free")
    context = _context()
    payload = _payload()

    async def success_iterator() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content={"ok": True})

    stream_handle = MagicMock()
    stream_handle.headers = {"x-request-id": "p-1"}
    stream_handle.cancel_callback = AsyncMock()
    stream_handle.iterator = success_iterator()

    transport = MagicMock()
    transport.initiate_streaming_request = AsyncMock(return_value=stream_handle)

    g55 = Gpt55FreePlanDowngradeConfig(
        enabled=True,
        proactive_enabled=True,
        reactive_enabled=True,
    )
    executor = ResponseExecutor(
        connector,
        credential_manager,
        max_retries=2,
        retry_backoff_seconds=(0.1, 0.2),
        transport=transport,
        gpt55_free_plan_downgrade=g55,
    )
    with stamina.set_testing(True, attempts=3, cap=True):
        result = await executor.execute(payload, context)
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.content is not None
        async for _ in result.content:
            break
    only = transport.initiate_streaming_request.call_args_list[0]
    assert only.args[1].get("model") == "gpt-5.4"
    assert transport.initiate_streaming_request.await_count == 1
