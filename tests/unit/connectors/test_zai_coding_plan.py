from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from src.connectors.openai import OpenAIConnector
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.common.exceptions import AuthenticationError, RateLimitExceededError
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.interfaces.response_processor_interface import ProcessedResponse


async def async_chunk_iterator(chunks: list[ProcessedResponse]):
    for chunk in chunks:
        yield chunk


def test_select_model_accepts_glm5_when_not_in_provider_list():
    """GLM 5.x must pass through even if /models omitted them."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )
    backend.available_models = ["glm-4.6"]
    assert backend._select_model("glm-5.1") == "glm-5.1"
    assert backend._select_model("zai-coding-plan:glm-5.0") == "glm-5.0"


def test_select_model_preserves_explicit_unknown_model():
    """Explicit model IDs should pass through even if not discovered."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )
    backend.available_models = ["glm-4.6"]
    assert backend._select_model("zai-coding-plan:glm-4.7") == "glm-4.7"


def test_supported_models_include_glm5():
    assert "glm-5.1" in ZaiCodingPlanBackend._SUPPORTED_MODELS
    assert "glm-5.0" in ZaiCodingPlanBackend._SUPPORTED_MODELS


@pytest.mark.asyncio
async def test_rate_limit_preserves_retry_after_details(mocker):
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )
    backend.available_models = ["glm-5.1"]
    backend._provider_models = set()

    from src.connectors.contracts import ConnectorChatCompletionsRequest
    from src.core.domain.chat import CanonicalChatRequest, ChatMessage

    request = ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="glm-5.1",
            messages=[ChatMessage(role="user", content="test")],
            stream=False,
        ),
        processed_messages=[ChatMessage(role="user", content="test")],
        effective_model="glm-5.1",
        identity=None,
        cancellation_coordinator=None,
        cancellation_token=None,
        context=None,
        options={},
    )

    mocker.patch.object(
        OpenAIConnector,
        "_chat_completions_canonical",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=429,
            detail={"message": "Too many requests", "headers": {"retry-after": "7"}},
        ),
    )

    with pytest.raises(RateLimitExceededError) as excinfo:
        await backend.chat_completions(request)

    assert excinfo.value.details["headers"]["retry-after"] == "7"
    assert excinfo.value.details["retry_after_seconds"] == 7.0


@pytest.mark.asyncio
async def test_health_check_reuses_cached_model_discovery(mocker):
    ZaiCodingPlanBackend._MODEL_DISCOVERY_CACHE.clear()
    mocker.patch.dict(
        "os.environ",
        {"ZAI_CODING_PLAN_API_KEY": "NOT-A-REAL-KEY-just-for-testing"},
    )
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "glm-5.1"}]}
    mock_client.get.return_value = mock_response

    backend = ZaiCodingPlanBackend(
        client=mock_client, config=MagicMock(), translation_service=MagicMock()
    )
    await backend.initialize()
    assert mock_client.get.await_count == 1

    healthy = await backend._perform_health_check()

    assert healthy is True
    assert mock_client.get.await_count == 1


@pytest.mark.asyncio
async def test_initialize_uses_windows_persistent_fallback_when_kwargs_missing(
    mocker,
) -> None:
    ZaiCodingPlanBackend._MODEL_DISCOVERY_CACHE.clear()
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "glm-5.1"}]}
    mock_client.get.return_value = mock_response

    mocker.patch(
        "src.connectors.zai_coding_plan.get_env_value_with_windows_persistent_fallback",
        return_value=("persistent-zai-key", "windows-user"),
    )

    backend = ZaiCodingPlanBackend(
        client=mock_client, config=MagicMock(), translation_service=MagicMock()
    )
    await backend.initialize()

    assert backend.api_key == "persistent-zai-key"


@pytest.mark.asyncio
async def test_initialize_prefers_kwargs_api_key_over_fallback(mocker) -> None:
    ZaiCodingPlanBackend._MODEL_DISCOVERY_CACHE.clear()
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "glm-5.1"}]}
    mock_client.get.return_value = mock_response

    mocker.patch(
        "src.connectors.zai_coding_plan.get_env_value_with_windows_persistent_fallback",
        return_value=("persistent-zai-key", "windows-user"),
    )

    backend = ZaiCodingPlanBackend(
        client=mock_client, config=MagicMock(), translation_service=MagicMock()
    )
    await backend.initialize(api_key="kwargs-zai-key")

    assert backend.api_key == "kwargs-zai-key"


@pytest.mark.asyncio
async def test_initialize_raises_when_no_api_key_available(mocker) -> None:
    mocker.patch(
        "src.connectors.zai_coding_plan.get_env_value_with_windows_persistent_fallback",
        return_value=(None, "missing"),
    )

    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )

    with pytest.raises(AuthenticationError) as excinfo:
        await backend.initialize()

    assert getattr(excinfo.value, "code", None) == "missing_api_key"


@pytest.mark.asyncio
async def test_temperature_from_request_data_is_applied(mocker):
    """
    Verify that the 'temperature' from request_data is correctly applied in the payload.
    """
    # 1. Mock dependencies for the constructor
    mock_client = AsyncMock()
    mock_config = MagicMock()

    # 2. Mock parent's _prepare_payload and other methods to isolate the test
    mocker.patch.object(
        OpenAIConnector,
        "_prepare_payload",
        new_callable=AsyncMock,
        return_value={"messages": []},
    )
    mocker.patch.object(
        ZaiCodingPlanBackend, "_select_model", return_value="test-model"
    )
    mocker.patch.object(
        ZaiCodingPlanBackend, "_extract_mcp_tool_calls_from_messages", return_value=[]
    )

    # 3. Instantiate the backend with mocks
    backend = ZaiCodingPlanBackend(
        client=mock_client, config=mock_config, translation_service=MagicMock()
    )
    # Disable model refresh for this unit test
    backend.available_models = ["test-model"]

    # 4. Create a mock request_data object with the desired temperature
    temperature_value = 1.0
    mock_request_data = MagicMock()
    mock_request_data.temperature = temperature_value
    mock_request_data.stream = False
    mock_request_data.max_tokens = None
    mock_request_data.top_p = None
    mock_request_data.tools = None
    mock_request_data.tool_choice = None
    mock_request_data.model = "test-model"
    # Add a messages attribute to the mock
    mock_request_data.messages = []

    # 5. Call the method under test
    payload = await backend._prepare_payload(
        request_data=mock_request_data, processed_messages=[]
    )

    # 6. Assert that the temperature in the payload is the one from request_data
    assert "temperature" in payload
    assert payload["temperature"] == temperature_value


@pytest.mark.asyncio
async def test_prepare_payload_preserves_small_max_tokens(mocker):
    """ZAI payload should not upsize small user-provided max_tokens values."""
    mock_client = AsyncMock()
    mock_config = MagicMock()

    mocker.patch.object(
        OpenAIConnector,
        "_prepare_payload",
        new_callable=AsyncMock,
        return_value={"messages": []},
    )
    mocker.patch.object(ZaiCodingPlanBackend, "_select_model", return_value="glm-5.1")
    mocker.patch.object(
        ZaiCodingPlanBackend, "_extract_mcp_tool_calls_from_messages", return_value=[]
    )

    backend = ZaiCodingPlanBackend(
        client=mock_client, config=mock_config, translation_service=MagicMock()
    )
    backend.available_models = ["glm-5.1"]
    backend._max_tokens_limit = 200000

    mock_request_data = MagicMock()
    mock_request_data.model = "glm-5.1"
    mock_request_data.stream = False
    mock_request_data.max_tokens = 256
    mock_request_data.temperature = None
    mock_request_data.top_p = None
    mock_request_data.tools = None
    mock_request_data.tool_choice = None

    payload = await backend._prepare_payload(
        request_data=mock_request_data, processed_messages=[]
    )

    assert payload["max_tokens"] == 256


@pytest.mark.asyncio
async def test_sensitive_headers_are_redacted_in_logs(mocker, caplog):
    """
    Verify that sensitive headers (Authorization, Set-Cookie, etc.) are redacted when logged.
    This test prevents secret leakage in production logs.
    """
    # 1. Mock dependencies
    mock_client = AsyncMock()
    mock_config = MagicMock()

    # 2. Mock parent's _prepare_payload and other methods to isolate the test
    mocker.patch.object(
        OpenAIConnector,
        "_prepare_payload",
        new_callable=AsyncMock,
        return_value={"messages": []},
    )
    mocker.patch.object(
        ZaiCodingPlanBackend, "_select_model", return_value="test-model"
    )
    mocker.patch.object(
        ZaiCodingPlanBackend, "_extract_mcp_tool_calls_from_messages", return_value=[]
    )

    # 3. Mock parent's _handle_non_streaming_response to avoid actual HTTP calls
    mock_response = MagicMock()
    mock_response.status_code = 200
    mocker.patch.object(
        OpenAIConnector,
        "_handle_non_streaming_response",
        new_callable=AsyncMock,
        return_value=mock_response,
    )

    # 4. Instantiate the backend with a test API key
    mocker.patch.dict(
        "os.environ",
        {"ZAI_CODING_PLAN_API_KEY": "NOT-A-REAL-KEY-just-for-testing"},
    )
    backend = ZaiCodingPlanBackend(
        client=mock_client,
        config=mock_config,
        translation_service=MagicMock(),
    )
    backend.available_models = ["test-model"]

    # 5. Create mock request data
    mock_request_data = MagicMock()
    mock_request_data.model = "test-model"
    mock_request_data.stream = False
    mock_request_data.messages = []

    # 6. Set API base URL
    backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"

    # 7. Enable logging capture for INFO level
    import logging

    caplog.set_level(logging.INFO)

    # 8. Call the method that triggers header logging
    import contextlib

    with contextlib.suppress(Exception):
        # We expect this to fail due to mocking, we just care about log output
        await backend._handle_non_streaming_response(
            url="https://api.z.ai/api/coding/paas/v4/chat/completions",
            payload={"model": "test-model", "messages": []},
            headers={"Authorization": "Bearer NOT-A-REAL-KEY-just-for-testing"},
            session_id="test-session",
        )

    # 9. Verify that sensitive headers are redacted in logs
    info_logs = [
        record.message for record in caplog.records if record.levelno == logging.INFO
    ]
    header_logs = [log for log in info_logs if "Headers" in log]

    # At least one header log should exist
    assert len(header_logs) > 0, "Expected header logging to occur"

    # Verify the API key is NOT logged in plain text
    for log in header_logs:
        assert (
            "NOT-A-REAL-KEY-just-for-testing" not in log
        ), f"Full API key should not appear in logs. Found in: {log}"
        assert (
            "***" in log or "[REDACTED]" in log
        ), f"Expected redaction marker in header log: {log}"


def test_get_headers_filters_non_standard_identity_headers() -> None:
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )
    backend.api_key = "NOT-A-REAL-KEY-just-for-testing"

    identity = AppIdentityConfig.model_validate(
        {
            "title": {
                "default_value": "Kilo Code",
                "passthrough_name": "x-title",
            },
            "url": {
                "default_value": "https://kilocode.ai",
                "passthrough_name": "http-referer",
            },
            "user_agent": {
                "default_value": "Kilo-Code/4.111.0",
                "passthrough_name": "user-agent",
            },
        }
    )

    raw_headers = backend.get_headers(identity=identity)
    # Simulate an injected B2BUA-style header and verify sanitization behavior
    raw_headers["X-Session-ID"] = "proxy-session"
    sanitized = backend._sanitize_outbound_headers(raw_headers)

    assert "X-Session-ID" not in sanitized
    assert sanitized["X-KiloCode-Version"] == backend._KILO_VERSION
    assert sanitized["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_stream_completion_uses_sse_accept_without_loop_guard(mocker) -> None:
    captured_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n\n",
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        backend = ZaiCodingPlanBackend(
            client=client,
            config=MagicMock(),
            translation_service=MagicMock(),
        )
        backend.api_key = "NOT-A-REAL-KEY-just-for-testing"
        backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"
        backend.available_models = ["glm-4.7"]
        backend._provider_models = set()
        backend._max_tokens_limit = 200000
        backend._default_max_tokens = 8192

        mocker.patch.object(
            ZaiCodingPlanBackend,
            "_prepare_payload",
            new_callable=AsyncMock,
            return_value={"model": "glm-4.7", "messages": [], "stream": True},
        )

        request = cast(
            Any,
            SimpleNamespace(
                model="glm-4.7",
                messages=[],
                extra_body=None,
                identity=None,
                stream=True,
                max_tokens=32,
                temperature=None,
                top_p=None,
                tools=None,
                tool_choice=None,
            ),
        )

        async for _ in backend.stream_completion(request):
            break

    assert captured_headers.get("accept") == "text/event-stream"
    assert "x-llmproxy-loop-guard" not in captured_headers
    assert captured_headers.get("user-agent") == backend._KILO_USER_AGENT


@pytest.mark.asyncio
async def test_streaming_wrapper_sanitizes_attempt_completion_for_non_default_model(
    mocker,
) -> None:
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )
    backend.api_key = "NOT-A-REAL-KEY-just-for-testing"
    backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"

    attempt_chunk = (
        'data: {"id":"resp-1","object":"chat.completion.chunk","model":"glm-5.1",'
        '"choices":[{"delta":{"content":"<attempt_completion><result>sanitized body</result>'
        '</attempt_completion>"},"finish_reason":"stop"}]}\n\n'
    )
    base_handle = SimpleNamespace(
        iterator=async_chunk_iterator([ProcessedResponse(content=attempt_chunk)]),
        cancel_callback=AsyncMock(),
        headers={},
    )
    mocker.patch.object(
        OpenAIConnector,
        "_handle_streaming_response",
        new_callable=AsyncMock,
        return_value=base_handle,
    )

    wrapped = await backend._handle_streaming_response(
        url=f"{backend.api_base_url}/chat/completions",
        payload={"model": "glm-5.1"},
        headers={"Authorization": "Bearer test"},
        session_id="session-1",
        stream_format="responses",
    )

    emitted = [chunk async for chunk in wrapped.iterator]

    assert any(
        isinstance(chunk.content, str) and "sanitized body" in chunk.content
        for chunk in emitted
    )
