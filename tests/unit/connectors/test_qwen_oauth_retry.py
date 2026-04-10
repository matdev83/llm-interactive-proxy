from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.usage_summary import UsageSummary

qwen_oauth = pytest.importorskip("llm_proxy_oauth_connectors.qwen_oauth")


def _get_openai_connector_class():
    from src.connectors.openai import OpenAIConnector as OpenAIConnectorRuntime

    return OpenAIConnectorRuntime


def _build_connector():
    connector = qwen_oauth.QwenOAuthConnector.__new__(qwen_oauth.QwenOAuthConnector)
    connector._enable_qwen_oauth_backend_debugging_override = True
    connector._refresh_token_if_needed = AsyncMock(return_value=True)
    connector._validate_runtime_credentials = AsyncMock(return_value=True)
    connector._load_oauth_credentials = AsyncMock(return_value=True)
    connector._credential_validation_errors = []
    connector._calculate_token_usage = MagicMock(return_value={})
    connector._initial_rate_limit_retry_enabled = True
    connector._initial_rate_limit_retry_max_wait_seconds = (
        qwen_oauth.INITIAL_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS
    )
    connector._initial_rate_limit_retry_random_min_seconds = (
        qwen_oauth.INITIAL_RATE_LIMIT_RETRY_RANDOM_MIN_SECONDS
    )
    connector._initial_rate_limit_retry_random_max_seconds = (
        qwen_oauth.INITIAL_RATE_LIMIT_RETRY_RANDOM_MAX_SECONDS
    )
    return connector


def _build_request():
    return SimpleNamespace(
        request=SimpleNamespace(),
        processed_messages=[{"role": "user", "content": "hello"}],
        effective_model="qwen-oauth:qwen/coder-model",
        cancellation_coordinator=None,
        cancellation_token=None,
    )


@pytest.mark.asyncio
async def test_qwen_oauth_retries_429_with_retry_after(monkeypatch):
    connector = _build_connector()
    request = _build_request()
    response = ResponseEnvelope(
        content={"choices": [{"message": {"content": "ok"}}]},
        usage=UsageSummary(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    retry_error = HTTPException(
        status_code=429,
        detail={"headers": {"Retry-After": "5"}},
    )
    base_call = AsyncMock(side_effect=[retry_error, response])
    sleep_mock = AsyncMock()

    monkeypatch.setattr(
        _get_openai_connector_class(),
        "_chat_completions_canonical",
        base_call,
    )
    monkeypatch.setattr(qwen_oauth.asyncio, "sleep", sleep_mock)

    result = await connector._chat_completions_canonical(request)

    assert result is response
    assert base_call.await_count == 2
    connector._load_oauth_credentials.assert_awaited_once()
    sleep_mock.assert_awaited_once_with(5.0)


@pytest.mark.asyncio
async def test_qwen_oauth_retries_429_with_random_delay(monkeypatch):
    connector = _build_connector()
    request = _build_request()
    response = ResponseEnvelope(
        content={"choices": [{"message": {"content": "ok"}}]},
        usage=UsageSummary(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    retry_error = HTTPException(status_code=429, detail={"message": "rate limited"})
    base_call = AsyncMock(side_effect=[retry_error, response])
    sleep_mock = AsyncMock()
    uniform_mock = MagicMock(return_value=4.25)

    monkeypatch.setattr(
        _get_openai_connector_class(),
        "_chat_completions_canonical",
        base_call,
    )
    monkeypatch.setattr(qwen_oauth.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(qwen_oauth.random, "uniform", uniform_mock)

    result = await connector._chat_completions_canonical(request)

    assert result is response
    assert base_call.await_count == 2
    connector._load_oauth_credentials.assert_awaited_once()
    sleep_mock.assert_awaited_once_with(4.25)
    uniform_mock.assert_called_once_with(
        qwen_oauth.INITIAL_RATE_LIMIT_RETRY_RANDOM_MIN_SECONDS,
        qwen_oauth.INITIAL_RATE_LIMIT_RETRY_RANDOM_MAX_SECONDS,
    )


@pytest.mark.asyncio
async def test_qwen_oauth_rejects_non_retryable_http_exception(monkeypatch):
    connector = _build_connector()
    request = _build_request()
    bad_request = HTTPException(status_code=400, detail={"message": "bad request"})
    base_call = AsyncMock(side_effect=bad_request)
    warning_mock = MagicMock()

    monkeypatch.setattr(
        _get_openai_connector_class(),
        "_chat_completions_canonical",
        base_call,
    )
    monkeypatch.setattr(qwen_oauth.logger, "warning", warning_mock)

    with pytest.raises(HTTPException) as exc_info:
        await connector._chat_completions_canonical(request)

    assert exc_info.value is bad_request
    assert base_call.await_count == 1
    assert warning_mock.called
    _, kwargs = warning_mock.call_args
    assert "exc_info" not in kwargs
