from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import requests  # type: ignore[import-untyped]
from requests.structures import CaseInsensitiveDict  # type: ignore[import-untyped]
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.policies import RateLimitRetryPolicy, RetryDecision
from src.connectors.gemini_base.retry_delay_parser import extract_retry_delay
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

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=None,
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-1",
        signature_session_id="sess-1",
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
    response.headers = CaseInsensitiveDict({"Retry-After": "0.1"})

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


@pytest.mark.asyncio
async def test_streaming_executor_retries_on_message_based_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.connectors.gemini_base import streaming_executor as module_under_test

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=None,
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-2",
        signature_session_id="sess-2",
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
    response._content = b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"You have exhausted your capacity on this model. Your quota will reset after 0.1s."}}'
    response.headers = CaseInsensitiveDict({})

    retry_policy = RateLimitRetryPolicy(retry_delay_extractor=extract_retry_delay)

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


@pytest.mark.asyncio
async def test_streaming_executor_retries_on_header_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.connectors.gemini_base import streaming_executor as module_under_test

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=None,
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-4",
        signature_session_id="sess-4",
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
    response.headers = CaseInsensitiveDict({"Retry-After": "0.1"})

    retry_policy = RateLimitRetryPolicy(retry_delay_extractor=extract_retry_delay)

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


@pytest.mark.asyncio
async def test_streaming_executor_retries_on_zero_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.connectors.gemini_base import streaming_executor as module_under_test

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=None,
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-3",
        signature_session_id="sess-3",
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
    response._content = b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"You have exhausted your capacity on this model. Your quota will reset after 0s."}}'
    response.headers = CaseInsensitiveDict({})

    retry_policy = RateLimitRetryPolicy(retry_delay_extractor=extract_retry_delay)

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

    # Zero retry-after windows must not result in a hot retry loop.
    sleep_mock.assert_awaited()
    assert sleep_mock.await_args is not None
    sleep_args = sleep_mock.await_args.args
    assert sleep_args[0] >= executor.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS

    assert any(chunk.content == "ok" for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_executor_emits_keepalive_when_upstream_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-keepalive",
        signature_session_id="sess-keepalive",
        build_request_body=lambda: {"request": {}},
    )

    translation_service = MagicMock()
    translation_service.to_domain_stream_chunk.return_value = {
        "choices": [{"delta": {"content": "ok"}}]
    }

    executor = StreamingExecutor(translation_service=translation_service)
    monkeypatch.setattr(executor, "STREAMING_KEEPALIVE_INTERVAL_SECONDS", 0.01)

    response = MagicMock()
    response.status_code = 200

    def _iter_content(chunk_size: int = 4096, decode_unicode: bool = False):
        time.sleep(0.05)
        yield (b'data: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}\n')
        yield b"data: [DONE]\n"

    response.iter_content = _iter_content
    response.close = MagicMock()

    prepared.auth_session.request.return_value = response

    processor = SSELineProcessor(
        translation_service=translation_service,
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini",
    )

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._stream_generator(
        prepared=prepared,
        url="https://example.invalid",
        processor=processor,
        prompt_tokens=0,
    ):
        chunks.append(chunk)

    assert any(bool(chunk.metadata.get("_keepalive")) for chunk in chunks)
    assert any(
        chunk.content for chunk in chunks if not chunk.metadata.get("_keepalive")
    )


@pytest.mark.asyncio
async def test_streaming_executor_emits_keepalive_before_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify keepalives are sent while waiting for the initial HTTP response."""
    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-pre-headers",
        signature_session_id="sess-pre-headers",
        build_request_body=lambda: {"request": {}},
    )

    translation_service = MagicMock()
    # Mock successful response
    response = MagicMock()
    response.status_code = 200
    response.iter_content = lambda **_: [b'data: {"choices": []}\n', b"data: [DONE]\n"]
    response.close = MagicMock()

    # Simulate slow response headers (e.g. backend processing a large prompt)
    def _slow_request(*args, **kwargs):
        time.sleep(0.1)  # Longer than keepalive interval
        return response

    prepared.auth_session.request = _slow_request

    executor = StreamingExecutor(translation_service=translation_service)
    # Set a very short keepalive interval for the test
    monkeypatch.setattr(executor, "STREAMING_KEEPALIVE_INTERVAL_SECONDS", 0.02)

    processor = SSELineProcessor(
        translation_service=translation_service,
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini",
    )

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._stream_generator(
        prepared=prepared,
        url="https://example.invalid",
        processor=processor,
        prompt_tokens=0,
    ):
        chunks.append(chunk)

    # We expect at least one keepalive before the actual response starts
    keepalives = [c for c in chunks if c.metadata.get("_keepalive")]
    assert len(keepalives) >= 1
    assert all(c.content == "" for c in keepalives)
    assert all(c.metadata["model"] == prepared.effective_model for c in keepalives)


@pytest.mark.asyncio
async def test_streaming_executor_handles_429_after_keepalive_during_header_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify 429 is handled correctly even if keepalives were sent while waiting for headers."""
    from src.connectors.gemini_base import streaming_executor as module_under_test

    # Mock sleep to avoid waiting during retry
    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-429-after-keepalive",
        signature_session_id="sess-429-after-keepalive",
        build_request_body=lambda: {"request": {}},
    )

    translation_service = MagicMock()
    translation_service.to_domain_stream_chunk.side_effect = lambda chunk, **_: (
        {"choices": [{"delta": {"content": "final"}}]} if chunk else None
    )

    # First response is a 429
    error_response = requests.Response()
    error_response.status_code = 429
    error_response._content = b'{"error":{"message":"Rate limited"}}'
    error_response.headers = CaseInsensitiveDict({"Retry-After": "0.01"})

    # Second response (retry) is a 200
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.iter_content = lambda **_: [
        b'data: {"candidates": [{"content": {"parts": [{"text": "final"}]}}]}\n',
        b"data: [DONE]\n",
    ]
    success_response.close = MagicMock()

    request_calls = 0

    def _slow_request(*args, **kwargs):
        nonlocal request_calls
        request_calls += 1
        time.sleep(0.05)  # Longer than keepalive interval
        if request_calls == 1:
            return error_response
        return success_response

    prepared.auth_session.request = _slow_request

    executor = StreamingExecutor(translation_service=translation_service)
    monkeypatch.setattr(executor, "STREAMING_KEEPALIVE_INTERVAL_SECONDS", 0.02)

    # Ensure we use a retry policy that allows at least one retry
    retry_policy = _RetryPolicyStub(sleep_seconds=0.01)

    processor = SSELineProcessor(
        translation_service=translation_service,
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini",
    )

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._stream_generator(
        prepared=prepared,
        url="https://example.invalid",
        processor=processor,
        prompt_tokens=0,
        retry_policy=retry_policy,
    ):
        chunks.append(chunk)

    # Should have keepalives from the first (slow) request attempt
    keepalives = [c for c in chunks if c.metadata.get("_keepalive")]
    assert len(keepalives) >= 1

    # Should have the final successful content from the second attempt
    assert any("final" in str(c.content) for c in chunks)
    assert request_calls == 2
