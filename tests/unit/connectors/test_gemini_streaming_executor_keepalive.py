from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import requests  # type: ignore[import-untyped]
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.policies import RetryDecision
from src.connectors.gemini_base.streaming_executor import (
    SSELineProcessor,
    StreamingExecutor,
)
from src.core.common.exceptions import BackendError
from src.core.interfaces.response_processor_interface import ProcessedResponse


class _RetryPolicyStub:
    def __init__(self, sleep_seconds: float) -> None:
        self._sleep_seconds = sleep_seconds

    def should_retry(
        self, error: BackendError, attempt: int, *, is_streaming: bool = False
    ) -> RetryDecision:
        return RetryDecision(should_retry=True, sleep_seconds=self._sleep_seconds)


@pytest.mark.asyncio
async def test_streaming_executor_emits_keepalive_during_internal_429_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Avoid real sleep in unit test.
    from src.connectors.gemini_base import streaming_executor as module_under_test

    monkeypatch.setattr(module_under_test.asyncio, "sleep", AsyncMock())

    prepared = PreparedChatRequest(
        auth_session=None,
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-1",
        build_request_body=dict,
    )

    executor = StreamingExecutor(translation_service=MagicMock())

    async def _fake_stream_generator(**_kwargs):
        yield ProcessedResponse(content="ok", metadata={})

    executor._stream_generator = _fake_stream_generator  # type: ignore[assignment]

    processor = SSELineProcessor(
        translation_service=MagicMock(),
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini",
    )

    response = requests.Response()
    response.status_code = 429
    response._content = (
        b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"Rate limited"}}'
    )
    response.headers = {"Retry-After": "0.1"}

    retry_policy = _RetryPolicyStub(sleep_seconds=0.1)

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._handle_error_response(
        response=response,
        processor=processor,
        prepared=prepared,
        url="https://example.invalid",
        prompt_tokens=0,
        retry_policy=retry_policy,
    ):
        chunks.append(chunk)

    assert any(bool(chunk.metadata.get("_keepalive")) for chunk in chunks)
    assert any(chunk.content == "ok" for chunk in chunks)
