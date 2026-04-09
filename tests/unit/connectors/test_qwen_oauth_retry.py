from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.usage_summary import UsageSummary

qwen_oauth = pytest.importorskip("llm_proxy_oauth_connectors.qwen_oauth")


def _build_connector():
    connector = qwen_oauth.QwenOAuthConnector.__new__(qwen_oauth.QwenOAuthConnector)
    connector._enable_qwen_oauth_backend_debugging_override = True
    connector._refresh_token_if_needed = AsyncMock(return_value=True)
    connector._validate_runtime_credentials = AsyncMock(return_value=True)
    connector._load_oauth_credentials = AsyncMock(return_value=True)
    connector._credential_validation_errors = []
    connector._calculate_token_usage = MagicMock()
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
async def test_qwen_oauth_retries_transient_quota_http_exception(monkeypatch):
    connector = _build_connector()
    request = _build_request()
    response = ResponseEnvelope(
        content={"choices": [{"message": {"content": "ok"}}]},
        usage=UsageSummary(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    quota_error = HTTPException(
        status_code=503,
        detail={
            "type": "quota_exceeded",
            "code": 503,
            "error": {
                "code": "insufficient_quota",
                "type": "quota_exceeded",
            },
        },
    )
    base_call = AsyncMock(side_effect=[quota_error, response])

    monkeypatch.setattr(
        "src.connectors.openai.OpenAIConnector._chat_completions_canonical",
        base_call,
    )
    sleep_mock = AsyncMock()
    monkeypatch.setattr(qwen_oauth.asyncio, "sleep", sleep_mock)

    result = await connector._chat_completions_canonical(request)

    assert result is response
    assert base_call.await_count == 2
    connector._load_oauth_credentials.assert_awaited_once()
    sleep_mock.assert_awaited_once_with(qwen_oauth.FALSE_QUOTA_RETRY_DELAY_SECONDS)


@pytest.mark.asyncio
async def test_qwen_oauth_reraises_http_exception_without_traceback(monkeypatch):
    connector = _build_connector()
    request = _build_request()
    bad_request = HTTPException(status_code=400, detail={"message": "bad request"})
    base_call = AsyncMock(side_effect=bad_request)
    warning_mock = MagicMock()

    monkeypatch.setattr(
        "src.connectors.openai.OpenAIConnector._chat_completions_canonical",
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
