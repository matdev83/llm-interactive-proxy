from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import requests  # type: ignore[import-untyped]
from requests.structures import CaseInsensitiveDict  # type: ignore[import-untyped]
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.policies import RetryDecision
from src.connectors.gemini_base.streaming_executor import (
    SSELineProcessor,
    StreamingExecutor,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse


class _RetryPolicyStub:
    def __init__(self, sleep_seconds: float) -> None:
        self._sleep_seconds = sleep_seconds

    def should_retry(
        self, error, attempt: int, *, is_streaming: bool = False
    ) -> RetryDecision:
        return RetryDecision(should_retry=True, sleep_seconds=self._sleep_seconds)


@pytest.mark.asyncio
async def test_streaming_executor_rotates_oauth_auto_on_429_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test rotation on 429 in late path (_handle_error_response)."""
    # Avoid real sleep in unit test.
    from src.connectors.gemini_base import streaming_executor as module_under_test

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-oauth-auto",
        signature_session_id="sess-oauth-auto",
        build_request_body=dict,
    )
    prepared.auth_session.headers = {"Authorization": "Bearer OLD"}

    executor = StreamingExecutor(translation_service=MagicMock())

    async def _fake_stream_generator(**_kwargs):
        yield ProcessedResponse(content="ok", metadata={})

    executor._stream_generator = _fake_stream_generator  # type: ignore[assignment]

    processor = SSELineProcessor(
        translation_service=MagicMock(),
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini-oauth-auto",
    )

    # 429 with a short retry-after window equal to the MIN floor, so the
    # computed delay is deterministic and testable in a single sleep call.
    response = requests.Response()
    response.status_code = 429
    response._content = (
        b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"Rate limited"}}'
    )
    response.headers = CaseInsensitiveDict({"Retry-After": "0.5"})

    retry_policy = _RetryPolicyStub(sleep_seconds=0.5)

    token_refresher = MagicMock()
    token_refresher.backend_type = "gemini-oauth-auto"
    token_refresher._oauth_credentials = {"access_token": "NEW"}
    token_refresher.refresh_token_if_needed = AsyncMock(return_value=True)

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._handle_error_response(
        response=response,
        processor=processor,
        prepared=prepared,
        url="https://example.invalid",
        prompt_tokens=0,
        retry_policy=retry_policy,
        token_refresher=token_refresher,
    ):
        chunks.append(chunk)

    # Token rotation should update the auth header for the retry attempt.
    assert prepared.auth_session.headers["Authorization"] == "Bearer NEW"

    # After rotation, the server's retry-after hint is honoured (IP-based
    # rate limits apply across all accounts, rotation does not help).
    assert sleep_mock.await_count >= 1
    assert (
        sleep_mock.await_args.args[0]
        >= executor.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS
    )

    assert any(chunk.content == "ok" for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_executor_preserves_affinity_on_short_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.connectors.gemini_base import streaming_executor as module_under_test

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-affinity",
        signature_session_id="sess-affinity",
        build_request_body=dict,
    )
    prepared.auth_session.headers = {"Authorization": "Bearer OLD"}

    executor = StreamingExecutor(translation_service=MagicMock())

    async def _fake_stream_generator(**_kwargs):
        yield ProcessedResponse(content="ok", metadata={})

    executor._stream_generator = _fake_stream_generator  # type: ignore[assignment]

    processor = SSELineProcessor(
        translation_service=MagicMock(),
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini-oauth-auto",
    )

    response = requests.Response()
    response.status_code = 429
    response._content = (
        b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"Rate limited"}}'
    )
    response.headers = CaseInsensitiveDict({"Retry-After": "17"})

    retry_policy = _RetryPolicyStub(sleep_seconds=17.0)

    token_refresher = MagicMock()
    token_refresher.backend_type = "gemini-oauth-auto"
    token_refresher.selection_strategy = "session-affinity"
    token_refresher._account_selector = MagicMock()
    token_refresher._account_selector.get_available_count = MagicMock(return_value=1)
    token_refresher._oauth_credentials = {"access_token": "NEW"}
    token_refresher.refresh_token_if_needed = AsyncMock(return_value=True)

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._handle_error_response(
        response=response,
        processor=processor,
        prepared=prepared,
        url="https://example.invalid",
        prompt_tokens=0,
        retry_policy=retry_policy,
        token_refresher=token_refresher,
    ):
        chunks.append(chunk)

    token_refresher.refresh_token_if_needed.assert_not_called()
    assert prepared.auth_session.headers["Authorization"] == "Bearer OLD"
    assert any(chunk.content == "ok" for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_executor_preserves_affinity_when_retry_after_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.connectors.gemini_base import streaming_executor as module_under_test

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-affinity-rotate",
        signature_session_id="sess-affinity-rotate",
        build_request_body=dict,
    )
    prepared.auth_session.headers = {"Authorization": "Bearer OLD"}

    executor = StreamingExecutor(translation_service=MagicMock())

    async def _fake_stream_generator(**_kwargs):
        yield ProcessedResponse(content="ok", metadata={})

    executor._stream_generator = _fake_stream_generator  # type: ignore[assignment]

    processor = SSELineProcessor(
        translation_service=MagicMock(),
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini-oauth-auto",
    )

    response = requests.Response()
    response.status_code = 429
    response._content = (
        b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"Rate limited"}}'
    )
    response.headers = CaseInsensitiveDict({"Retry-After": "0.5"})

    retry_policy = _RetryPolicyStub(sleep_seconds=0.5)

    token_refresher = MagicMock()
    token_refresher.backend_type = "gemini-oauth-auto"
    token_refresher.selection_strategy = "session-affinity"
    token_refresher._account_selector = MagicMock()
    token_refresher._account_selector.get_available_count = MagicMock(return_value=2)
    token_refresher._oauth_credentials = {"access_token": "NEW"}
    token_refresher.refresh_token_if_needed = AsyncMock(return_value=True)

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._handle_error_response(
        response=response,
        processor=processor,
        prepared=prepared,
        url="https://example.invalid",
        prompt_tokens=0,
        retry_policy=retry_policy,
        token_refresher=token_refresher,
    ):
        chunks.append(chunk)

    # With session-affinity and explicit retry-after, preserve current account.
    token_refresher.refresh_token_if_needed.assert_not_called()
    assert prepared.auth_session.headers["Authorization"] == "Bearer OLD"
    # The server hint is still honoured for the wait duration.
    assert sleep_mock.await_count >= 1
    assert (
        sleep_mock.await_args.args[0]
        >= executor.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS
    )
    assert any(chunk.content == "ok" for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_executor_rotates_when_retry_after_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.connectors.gemini_base import streaming_executor as module_under_test

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-affinity-missing-retry-after",
        signature_session_id="sess-affinity-missing-retry-after",
        build_request_body=dict,
    )
    prepared.auth_session.headers = {"Authorization": "Bearer OLD"}

    executor = StreamingExecutor(translation_service=MagicMock())

    async def _fake_stream_generator(**_kwargs):
        yield ProcessedResponse(content="ok", metadata={})

    executor._stream_generator = _fake_stream_generator  # type: ignore[assignment]

    processor = SSELineProcessor(
        translation_service=MagicMock(),
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini-oauth-auto",
    )

    response = requests.Response()
    response.status_code = 429
    response._content = (
        b'{"error":{"status":"RATE_LIMIT","message":"capacity throttled"}}'
    )
    response.headers = CaseInsensitiveDict({})

    retry_policy = _RetryPolicyStub(sleep_seconds=2.0)

    token_refresher = MagicMock()
    token_refresher.backend_type = "gemini-oauth-auto"
    token_refresher.selection_strategy = "session-affinity"
    token_refresher._account_selector = MagicMock()
    token_refresher._account_selector.get_available_count = MagicMock(return_value=2)
    token_refresher._oauth_credentials = {"access_token": "NEW"}
    token_refresher.refresh_token_if_needed = AsyncMock(return_value=True)

    chunks: list[ProcessedResponse] = []
    async for chunk in executor._handle_error_response(
        response=response,
        processor=processor,
        prepared=prepared,
        url="https://example.invalid",
        prompt_tokens=0,
        retry_policy=retry_policy,
        token_refresher=token_refresher,
    ):
        chunks.append(chunk)

    token_refresher.refresh_token_if_needed.assert_awaited_once()
    assert prepared.auth_session.headers["Authorization"] == "Bearer NEW"
    assert sleep_mock.await_count >= 1
    assert any(chunk.content == "ok" for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_executor_long_retry_after_surfaces_when_rotation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.connectors.gemini_base import streaming_executor as module_under_test
    from src.core.common.exceptions import BackendError

    sleep_mock = AsyncMock()
    monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-long-retry",
        signature_session_id="sess-long-retry",
        build_request_body=dict,
    )
    prepared.auth_session.headers = {"Authorization": "Bearer OLD"}

    executor = StreamingExecutor(translation_service=MagicMock())
    processor = SSELineProcessor(
        translation_service=MagicMock(),
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini-oauth-auto",
    )

    response = requests.Response()
    response.status_code = 429
    response._content = (
        b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"Rate limited"}}'
    )
    response.headers = CaseInsensitiveDict({"Retry-After": "120"})

    retry_policy = _RetryPolicyStub(sleep_seconds=120.0)

    token_refresher = MagicMock()
    token_refresher.backend_type = "gemini-oauth-auto"
    token_refresher.selection_strategy = "session-affinity"
    token_refresher.refresh_token_if_needed = AsyncMock(return_value=False)

    with pytest.raises(BackendError):
        async for _chunk in executor._handle_error_response(
            response=response,
            processor=processor,
            prepared=prepared,
            url="https://example.invalid",
            prompt_tokens=0,
            retry_policy=retry_policy,
            token_refresher=token_refresher,
        ):
            pass

    token_refresher.refresh_token_if_needed.assert_awaited_once()
    await_args = token_refresher.refresh_token_if_needed.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["retry_after_seconds"] == 120.0
    assert sleep_mock.await_count == 0


@pytest.mark.asyncio
async def test_streaming_executor_long_retry_after_stays_retryable_rate_limit() -> None:
    from src.core.common.exceptions import BackendError

    prepared = PreparedChatRequest(
        auth_session=MagicMock(),
        project_id="p",
        canonical_request=None,
        code_assist_request={},
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-pro-high",
        session_id="sess-long-retry-code",
        signature_session_id="sess-long-retry-code",
        build_request_body=dict,
    )

    executor = StreamingExecutor(translation_service=MagicMock())
    processor = SSELineProcessor(
        translation_service=MagicMock(),
        effective_model=prepared.effective_model,
        retry_delay_extractor=None,
        backend_type="gemini-oauth-auto",
    )

    response = requests.Response()
    response.status_code = 429
    response._content = (
        b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"Rate limited"}}'
    )
    response.headers = CaseInsensitiveDict({"Retry-After": "120"})

    with pytest.raises(BackendError) as exc_info:
        async for _chunk in executor._handle_error_response(
            response=response,
            processor=processor,
            prepared=prepared,
            url="https://example.invalid",
            prompt_tokens=0,
            retry_policy=None,
            token_refresher=None,
        ):
            pass

    assert exc_info.value.code == "rate_limit_exceeded"


def test_streaming_executor_has_timeout_rotation_logic() -> None:
    from pathlib import Path

    repo_root = Path(__file__).parent.parent.parent.parent
    executor_path = (
        repo_root / "src" / "connectors" / "gemini_base" / "streaming_executor.py"
    )
    source = executor_path.read_text(encoding="utf-8")

    checks = [
        "except requests.exceptions.Timeout",
        "_timeout_retry_attempted",
        "_try_rotate_oauth_auto_account",
        "Account rotation on timeout",
    ]
    for check in checks:
        assert check in source


def test_streaming_executor_uses_affinity_aware_rotation_helpers() -> None:
    from pathlib import Path

    repo_root = Path(__file__).parent.parent.parent.parent
    executor_path = (
        repo_root / "src" / "connectors" / "gemini_base" / "streaming_executor.py"
    )
    source = executor_path.read_text(encoding="utf-8")

    assert "_should_wait_same_account_on_rate_limit" in source
    assert source.count("_try_rotate_oauth_auto_account(") >= 3
