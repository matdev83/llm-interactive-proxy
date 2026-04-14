"""Upstream HTTP error mapping for OpenAIConnector (domain exceptions, not HTTPException)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.openai import OpenAIConnector, _extract_connector_chat_request
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
    RateLimitExceededError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


@pytest.fixture
def openai_connector() -> OpenAIConnector:
    client = AsyncMock(spec=httpx.AsyncClient)
    config = MagicMock(spec=AppConfig)
    config.streaming_yield_interval = 100
    connector = OpenAIConnector(
        client=client,
        config=config,
        translation_service=TranslationService(),
    )
    connector.api_key = "sk-test"
    connector.api_base_url = "https://api.openai.com/v1"
    connector.disable_health_check()
    return connector


@pytest.mark.asyncio
async def test_non_streaming_400_raises_invalid_request(
    openai_connector: OpenAIConnector,
) -> None:
    payload = {
        "error": {"message": "bad", "type": "invalid_request_error", "code": "invalid"}
    }
    response = httpx.Response(400, json=payload, request=_req())
    openai_connector._send_request_with_retry = AsyncMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(InvalidRequestError) as exc_info:
        await openai_connector._handle_non_streaming_response(
            "https://api.openai.com/v1/chat/completions",
            {"model": "gpt-4"},
            {"Authorization": "Bearer sk-test"},
            "sid",
            None,
        )
    assert exc_info.value.status_code == 400
    assert (
        "bad" in str(exc_info.value.message).lower() or exc_info.value.message == "bad"
    )


@pytest.mark.asyncio
async def test_non_streaming_502_raises_backend_error(
    openai_connector: OpenAIConnector,
) -> None:
    response = httpx.Response(
        502,
        json={"message": "upstream"},
        request=_req(),
    )
    openai_connector._send_request_with_retry = AsyncMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(BackendError) as exc_info:
        await openai_connector._handle_non_streaming_response(
            "https://api.openai.com/v1/chat/completions",
            {"model": "gpt-4"},
            {"Authorization": "Bearer sk-test"},
            "sid",
            None,
        )
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_non_streaming_429_raises_rate_limit_exceeded(
    openai_connector: OpenAIConnector,
) -> None:
    response = httpx.Response(
        429,
        json={"error": {"message": "rate", "type": "rate_limit"}},
        headers={"retry-after": "12"},
        request=_req(),
    )
    openai_connector._send_request_with_retry = AsyncMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(RateLimitExceededError) as exc_info:
        await openai_connector._handle_non_streaming_response(
            "https://api.openai.com/v1/chat/completions",
            {"model": "gpt-4"},
            {"Authorization": "Bearer sk-test"},
            "sid",
            None,
        )
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_streaming_429_insufficient_quota_raises_backend_error_503(
    openai_connector: OpenAIConnector,
) -> None:
    body = '{"error":{"message":"You exceeded your current quota","type":"insufficient_quota","code":"insufficient_quota"}}'
    response = MagicMock()
    response.status_code = 429
    response.headers = httpx.Headers({"content-type": "application/json"})

    async def aread() -> bytes:
        return body.encode()

    response.aread = aread
    response.aclose = AsyncMock()
    response.text = body

    openai_connector._send_request_with_retry = AsyncMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(BackendError) as exc_info:
        await openai_connector._handle_streaming_response(
            "https://api.openai.com/v1/chat/completions",
            {"model": "gpt-4"},
            {"Authorization": "Bearer sk-test"},
            "sid",
            "openai",
            None,
        )
    assert exc_info.value.status_code == 503
    details = exc_info.value.details or {}
    assert details.get("type") == "quota_exceeded" or (
        isinstance(details.get("error"), dict)
        and details.get("error", {}).get("type") == "quota_exceeded"
    )


@pytest.mark.asyncio
async def test_streaming_400_codex_instructions_invalid(
    openai_connector: OpenAIConnector,
) -> None:
    body = '{"detail":"Instructions are not valid"}'
    response = MagicMock()
    response.status_code = 400
    response.headers = httpx.Headers({})

    async def aread() -> bytes:
        return body.encode()

    response.aread = aread
    response.aclose = AsyncMock()
    response.text = body

    openai_connector._send_request_with_retry = AsyncMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(InvalidRequestError) as exc_info:
        await openai_connector._handle_streaming_response(
            "https://api.openai.com/v1/chat/completions",
            {"model": "gpt-4"},
            {"Authorization": "Bearer sk-test"},
            "sid",
            "openai",
            None,
        )
    assert exc_info.value.status_code == 400
    assert "codex_instructions_invalid" in str(exc_info.value.details)


def test_extract_connector_chat_request_accepts_simple_namespace() -> None:
    domain = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    raw = SimpleNamespace(
        request=domain,
        processed_messages=list(domain.messages),
        effective_model="gpt-4",
        identity=None,
        cancellation_coordinator=None,
        cancellation_token=None,
        context=None,
        options={"openai_url": "https://x/v1"},
    )
    ctx = _extract_connector_chat_request(raw)
    assert ctx.domain_request is domain
    assert ctx.effective_model == "gpt-4"
    assert ctx.options == {"openai_url": "https://x/v1"}


def test_extract_connector_chat_request_missing_request_raises() -> None:
    raw = SimpleNamespace(processed_messages=[])
    with pytest.raises(TypeError, match="missing required"):
        _extract_connector_chat_request(raw)


@pytest.mark.asyncio
async def test_chat_completions_streaming_propagates_authentication_error(
    openai_connector: OpenAIConnector,
) -> None:
    """integrate_streaming_pipeline must see AuthenticationError, not HTTPException."""
    streaming_req = ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=10,
            stream=True,
        ),
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="gpt-4",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="r1", session_id="s1", client_host=None, extensions={}
        ),
        options={},
    )
    # Pipeline entrypoint must propagate domain auth failures (local import in openai.py).
    with (
        patch(
            "src.core.ports.streaming_integration.integrate_streaming_pipeline",
            new_callable=AsyncMock,
            side_effect=AuthenticationError(message="bad creds"),
        ),
        pytest.raises(AuthenticationError, match="bad creds"),
    ):
        await openai_connector.chat_completions(streaming_req)


def test_domain_error_maps_to_http_for_wire_shape() -> None:
    exc = InvalidRequestError(
        message="bad request",
        details={"foo": "bar"},
        status_code=400,
    )
    http_exc = map_domain_exception_to_http_exception(exc)
    assert http_exc.status_code == 400
    assert isinstance(http_exc.detail, dict)


@pytest.mark.asyncio
async def test_non_streaming_json_decode_uses_text_for_details(
    openai_connector: OpenAIConnector,
) -> None:
    response = httpx.Response(
        422,
        content=b"plain error body",
        request=_req(),
    )
    openai_connector._send_request_with_retry = AsyncMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(InvalidRequestError):
        await openai_connector._handle_non_streaming_response(
            "https://api.openai.com/v1/chat/completions",
            {"model": "gpt-4"},
            {"Authorization": "Bearer sk-test"},
            "sid",
            None,
        )


@pytest.mark.asyncio
async def test_accumulator_maps_rate_limit_domain_error_to_envelope() -> None:
    from src.connectors.gemini_base.response_accumulator import (
        StreamingResponseAccumulator,
    )
    from src.core.domain.responses import StreamingResponseEnvelope

    async def failing():
        raise RateLimitExceededError(
            message="too many",
            details={"headers": {"retry-after": "5"}},
        )
        if False:
            yield None  # pragma: no cover - makes this an async generator

    env = StreamingResponseEnvelope(
        content=failing(),
        media_type="text/event-stream",
        headers={},
    )
    acc = StreamingResponseAccumulator(backend_type="openai-codex")
    out = await acc.accumulate(env)
    assert isinstance(out, ResponseEnvelope)
    assert out.status_code == 429


@pytest.mark.asyncio
async def test_non_streaming_401_raises_authentication_error(
    openai_connector: OpenAIConnector,
) -> None:
    """A real OpenAI 401 (auth failure) must raise AuthenticationError, not InvalidRequestError."""
    payload = {
        "error": {
            "message": "Incorrect API key provided.",
            "type": "authentication_error",
            "code": "invalid_api_key",
        }
    }
    response = httpx.Response(401, json=payload, request=_req())
    openai_connector._send_request_with_retry = AsyncMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(AuthenticationError) as exc_info:
        await openai_connector._handle_non_streaming_response(
            "https://api.openai.com/v1/chat/completions",
            {"model": "gpt-4"},
            {"Authorization": "Bearer sk-test"},
            "sid",
            None,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_non_streaming_403_raises_invalid_request_error(
    openai_connector: OpenAIConnector,
) -> None:
    payload = {
        "error": {
            "message": "Policy denied this request.",
            "type": "policy_error",
            "code": "policy_denied",
        }
    }
    response = httpx.Response(403, json=payload, request=_req())
    openai_connector._send_request_with_retry = AsyncMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(InvalidRequestError) as exc_info:
        await openai_connector._handle_non_streaming_response(
            "https://api.openai.com/v1/chat/completions",
            {"model": "gpt-4"},
            {"Authorization": "Bearer sk-test"},
            "sid",
            None,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_responses_method_uses_request_context(
    openai_connector: OpenAIConnector,
) -> None:
    """The responses method must pick up request.context, not just options."""
    req = ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
        ),
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="gpt-4o",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="test-req-123",
            session_id="test-sess-456",
            client_host="127.0.0.1",
            extensions={},
        ),
        options={},
    )
    # Mock the HTTP call to return a valid response
    response = httpx.Response(
        200,
        json={"id": "r1", "output": [], "status": "completed", "model": "gpt-4o"},
        request=_req(),
    )
    captured_context = None

    async def mock_send(**kwargs: object) -> httpx.Response:  # type: ignore[misc]
        nonlocal captured_context
        capture = kwargs.get("capture")
        if capture is not None:
            captured_context = getattr(capture, "context", None)
        return response

    openai_connector._send_request_with_retry = AsyncMock(side_effect=mock_send)  # type: ignore[method-assign]

    result = await openai_connector.responses(req)
    assert isinstance(result, ResponseEnvelope)
    # The context must be passed to the HTTP layer for correlation
    assert captured_context is not None
    assert captured_context.request_id == "test-req-123"
    assert captured_context.session_id == "test-sess-456"
    assert captured_context.client_host == "127.0.0.1"
