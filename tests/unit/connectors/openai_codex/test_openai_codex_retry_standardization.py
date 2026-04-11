"""Standardization tests for Codex retry integration."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import cast
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
from src.connectors.openai_codex.interfaces import ICredentialManager
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


def _build_context(*, stream: bool) -> CodexRequestContext:
    request = CanonicalChatRequest(
        model="gpt-5.1-codex",
        messages=[ChatMessage(role="user", content="hello")],
        stream=stream,
    )
    return CodexRequestContext(
        request=request,
        processed_messages=[
            ProcessedMessage(role="user", content="hello", tool_calls=None)
        ],
        effective_model="gpt-5.1-codex",
        capabilities=CodexClientCapabilities(),
        session_id="standardization-session",
    )


def _build_payload(*, stream: bool) -> CodexPayload:
    return CodexPayload(
        model="gpt-5.1-codex",
        input=[],
        tools=[],
        tool_choice="auto",
        parallel_tool_calls=False,
        store=False,
        stream=stream,
        include=[],
        prompt_cache_key="standardization-key",
    )


def _build_connector_mock() -> MagicMock:
    connector = MagicMock()
    connector.client = MagicMock()
    connector.translation_service = MagicMock()
    connector.get_headers = MagicMock(
        return_value={"Authorization": "Bearer test-token"}
    )
    connector.update_quota_headers = MagicMock()
    connector._degrade = MagicMock()
    return connector


def _build_credential_manager_mock() -> MagicMock:
    manager = MagicMock(spec=ICredentialManager)
    manager.refresh_access_token = AsyncMock(return_value=True)
    manager.get_access_token = MagicMock(return_value="fresh-token")
    manager.get_account_id = MagicMock(return_value=None)
    return manager


@pytest.mark.asyncio
async def test_non_streaming_401_refreshes_and_retries_once() -> None:
    connector = _build_connector_mock()
    credential_manager = _build_credential_manager_mock()
    context = _build_context(stream=False)
    payload = _build_payload(stream=False)

    unauthorized_response = MagicMock()
    unauthorized_response.status_code = 401
    unauthorized_response.json.return_value = {"error": "unauthorized"}
    unauthorized_response.text = '{"error":"unauthorized"}'
    unauthorized_response.headers = {}

    success_response = MagicMock()
    success_response.status_code = 200
    success_response.json.return_value = {"id": "ok", "choices": []}
    success_response.headers = {"x-request-id": "req-1"}

    connector.client.post = AsyncMock(
        side_effect=[unauthorized_response, success_response]
    )
    domain_response = MagicMock()
    domain_response.model_dump.return_value = {"content": "ok"}
    domain_response.usage = {"total_tokens": 1}
    connector.translation_service.to_domain_response.return_value = domain_response

    executor = ResponseExecutor(
        connector,
        credential_manager,
        max_retries=2,
        retry_backoff_seconds=(0.2, 0.4),
    )

    with stamina.set_testing(True, attempts=3, cap=True):
        result = await executor.execute(payload, context)

    assert isinstance(result, ResponseEnvelope)
    assert connector.client.post.await_count == 2
    assert credential_manager.refresh_access_token.await_count == 1


@pytest.mark.asyncio
async def test_non_streaming_refresh_failure_surfaces_deterministic_context() -> None:
    connector = _build_connector_mock()
    credential_manager = _build_credential_manager_mock()
    credential_manager.refresh_access_token = AsyncMock(return_value=False)
    context = _build_context(stream=False)
    payload = _build_payload(stream=False)

    unauthorized_response = MagicMock()
    unauthorized_response.status_code = 401
    unauthorized_response.json.return_value = {"error": "unauthorized"}
    unauthorized_response.text = '{"error":"unauthorized"}'
    unauthorized_response.headers = {}
    connector.client.post = AsyncMock(return_value=unauthorized_response)

    executor = ResponseExecutor(
        connector,
        credential_manager,
        max_retries=1,
        retry_backoff_seconds=(0.2,),
    )

    with (
        stamina.set_testing(True, attempts=3, cap=True),
        pytest.raises(HTTPException) as exc_info,
    ):
        await executor.execute(payload, context)

    detail = exc_info.value.detail
    assert exc_info.value.status_code == 401
    assert isinstance(detail, dict)
    detail_dict = cast(dict[str, object], detail)
    assert detail_dict["error"] == "openai_codex_auth_failed"
    details = cast(dict[str, object], detail_dict["details"])
    assert details["max_retries"] == 1
    assert "attempts" in details


@pytest.mark.asyncio
async def test_streaming_auth_error_after_visible_output_does_not_restart() -> None:
    connector = _build_connector_mock()
    credential_manager = _build_credential_manager_mock()
    context = _build_context(stream=True)
    payload = _build_payload(stream=True)

    async def stream_iterator() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content={"choices": [{"delta": {"content": "hi"}}]})
        yield ProcessedResponse(
            content={"error": "auth_failed", "details": {"status": 401}}
        )

    stream_handle = MagicMock()
    stream_handle.headers = {"x-request-id": "stream-1"}
    stream_handle.cancel_callback = AsyncMock()
    stream_handle.iterator = stream_iterator()

    transport = MagicMock()
    transport.initiate_streaming_request = AsyncMock(return_value=stream_handle)

    executor = ResponseExecutor(
        connector,
        credential_manager,
        max_retries=2,
        retry_backoff_seconds=(0.2, 0.4),
        transport=transport,
    )

    with stamina.set_testing(True, attempts=3, cap=True):
        result = await executor.execute(payload, context)
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.content is not None
        chunks = [chunk async for chunk in result.content]

    assert len(chunks) == 2
    assert transport.initiate_streaming_request.await_count == 1
    assert credential_manager.refresh_access_token.await_count == 0


def test_no_direct_asyncio_sleep_remains_in_auth_retry_loops() -> None:
    source = inspect.getsource(ResponseExecutor)
    assert "await asyncio.sleep(delay)" not in source
