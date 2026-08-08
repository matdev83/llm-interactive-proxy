"""Tests for the Alibaba international Token Plan connector."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.alibaba_token_plan_intl import (
    ALIBABA_TOKEN_PLAN_INTL_DEFAULT_BASE_URL,
    AlibabaTokenPlanIntlBackend,
)
from src.connectors.anthropic import AnthropicBackend
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import ConfigurationError, InvalidRequestError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService


def _backend() -> AlibabaTokenPlanIntlBackend:
    return AlibabaTokenPlanIntlBackend(
        client=httpx.AsyncClient(),
        config=MagicMock(spec=AppConfig),
        translation_service=TranslationService(),
    )


@pytest.mark.asyncio
async def test_initialize_uses_anthropic_defaults_and_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALIBABA_TOKEN_PLAN_API_KEY", "env-secret")
    backend = _backend()

    with (
        patch.object(backend, "list_models", new_callable=AsyncMock),
        patch(
            "src.connectors.alibaba_token_plan_intl.get_env_value_with_windows_persistent_fallback",
            return_value=("env-secret", "process"),
        ),
    ):
        await backend.initialize()

    assert backend.backend_type == "alibaba-token-plan-intl"
    assert backend.key_name == "alibaba-token-plan-intl"
    assert backend.api_key == "env-secret"
    assert backend.auth_header_name == "x-api-key"
    assert backend.anthropic_api_base_url == ALIBABA_TOKEN_PLAN_INTL_DEFAULT_BASE_URL
    await backend.client.aclose()


@pytest.mark.asyncio
async def test_initialize_allows_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALIBABA_TOKEN_PLAN_API_KEY", "env-secret")
    backend = _backend()

    with (
        patch.object(backend, "list_models", new_callable=AsyncMock),
        patch(
            "src.connectors.alibaba_token_plan_intl.get_env_value_with_windows_persistent_fallback",
            return_value=("env-secret", "process"),
        ),
    ):
        await backend.initialize(
            anthropic_api_base_url="https://proxy.example/anthropic/"
        )

    assert backend.anthropic_api_base_url == "https://proxy.example/anthropic"
    await backend.client.aclose()


@pytest.mark.asyncio
async def test_initialize_never_accepts_api_key_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALIBABA_TOKEN_PLAN_API_KEY", raising=False)
    backend = _backend()

    with (
        patch(
            "src.connectors.alibaba_token_plan_intl.get_env_value_with_windows_persistent_fallback",
            return_value=(None, "missing"),
        ),
        pytest.raises(ConfigurationError, match="ALIBABA_TOKEN_PLAN_API_KEY"),
    ):
        await backend.initialize(api_key="config-secret")

    await backend.client.aclose()


@pytest.mark.asyncio
async def test_model_discovery_uses_token_plan_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALIBABA_TOKEN_PLAN_API_KEY", "env-secret")

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/models"
        )
        assert request.headers["x-api-key"] == "env-secret"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": "qwen3.7-plus"}, {"id": "glm-5.2"}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    backend = AlibabaTokenPlanIntlBackend(
        client=client,
        config=MagicMock(spec=AppConfig),
        translation_service=TranslationService(),
    )
    with patch(
        "src.connectors.alibaba_token_plan_intl.get_env_value_with_windows_persistent_fallback",
        return_value=("env-secret", "process"),
    ):
        await backend.initialize()

    assert await backend.get_available_models_async() == [
        "alibaba-token-plan-intl/qwen3.7-plus",
        "alibaba-token-plan-intl/glm-5.2",
    ]
    await client.aclose()


def test_payload_normalizes_openai_tools_for_anthropic_api() -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="check status")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a command",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                    },
                },
            }
        ],
        tool_choice="auto",
    )

    payload = backend._prepare_anthropic_payload(
        request,
        [ChatMessage(role="user", content="check status")],
        "qwen3.7-plus",
        None,
    )

    assert payload["tools"] == [
        {
            "name": "bash",
            "description": "Run a command",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        }
    ]
    assert "tool_choice" not in payload


@pytest.mark.parametrize("tool_choice", ["required", "any", {"type": "function"}])
def test_payload_rejects_unsupported_tool_choice(tool_choice: object) -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="check status")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice=cast(str | dict[str, Any], tool_choice),
    )

    with pytest.raises(InvalidRequestError, match="supports only tool_choice"):
        backend._prepare_anthropic_payload(
            request,
            [ChatMessage(role="user", content="check status")],
            "qwen3.7-plus",
            None,
        )


@pytest.mark.parametrize("tool_choice", ["required", {"type": "function"}])
def test_payload_rejects_unsupported_tool_choice_without_tools(
    tool_choice: object,
) -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="check status")],
        tool_choice=cast(str | dict[str, Any], tool_choice),
    )

    with pytest.raises(InvalidRequestError, match="supports only tool_choice"):
        backend._prepare_anthropic_payload(
            request,
            [ChatMessage(role="user", content="check status")],
            "qwen3.7-plus",
            None,
        )


@pytest.mark.parametrize(
    "tool",
    [{}, {"type": "function", "function": {}}, {"name": ""}],
)
def test_payload_rejects_invalid_tool_definition(tool: object) -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="check status")],
        tools=cast(list[dict[str, Any]], [tool]),
    )

    with pytest.raises(InvalidRequestError, match="Invalid tool definition at index 0"):
        backend._prepare_anthropic_payload(
            request,
            [ChatMessage(role="user", content="check status")],
            "qwen3.7-plus",
            None,
        )


def test_payload_preserves_native_anthropic_tool_definition() -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="check status")],
        tools=[
            {
                "name": "bash",
                "description": "Run a command",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                },
            }
        ],
    )

    payload = backend._prepare_anthropic_payload(
        request,
        [ChatMessage(role="user", content="check status")],
        "qwen3.7-plus",
        None,
    )

    assert payload["tools"] == request.tools


def test_payload_tool_choice_none_omits_tools() -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="check status")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice="none",
    )

    payload = backend._prepare_anthropic_payload(
        request,
        [ChatMessage(role="user", content="check status")],
        "qwen3.7-plus",
        None,
    )

    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_payload_preserves_structured_tool_history() -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="unused")],
    )
    payload = backend._prepare_anthropic_payload(
        request,
        [
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=cast(
                    Any,
                    [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "arguments": '{"command":"git status"}',
                            },
                        }
                    ],
                ),
            ),
            ChatMessage(role="tool", content="clean", tool_call_id="call_1"),
        ],
        "qwen3.7-plus",
        None,
    )

    assert payload["messages"][0]["role"] == "assistant"
    assert any(
        block["type"] == "tool_use" for block in payload["messages"][0]["content"]
    )
    assert payload["messages"][1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "clean",
            }
        ],
    }


def test_payload_preserves_assistant_role_in_conversation_history() -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="unused")],
    )

    payload = backend._prepare_anthropic_payload(
        request,
        [
            ChatMessage(role="system", content="rules"),
            ChatMessage(role="assistant", content="previous answer"),
            ChatMessage(role="developer", content="extra rules"),
            ChatMessage(role="user", content="question"),
        ],
        "qwen3.7-plus",
        None,
    )

    assert payload["system"] == "rules"
    assert payload["messages"] == [
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "extra rules"},
        {"role": "user", "content": "question"},
    ]


def test_payload_preserves_interleaved_reasoning_before_tool_use() -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.8-max-preview",
        messages=[ChatMessage(role="user", content="unused")],
        reasoning_effort="high",
    )

    payload = backend._prepare_anthropic_payload(
        request,
        [
            ChatMessage(role="user", content="Inspect the repository"),
            ChatMessage(
                role="assistant",
                content="",
                reasoning_content="I need to inspect the steering files first.",
                tool_calls=cast(
                    Any,
                    [
                        {
                            "id": "toolu_1",
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "arguments": '{"command":"git log -5"}',
                            },
                        }
                    ],
                ),
            ),
            ChatMessage(
                role="tool",
                tool_call_id="toolu_1",
                content="commit output",
            ),
        ],
        "qwen3.8-max-preview",
        None,
    )

    assistant_content = payload["messages"][1]["content"]
    assert assistant_content[0] == {
        "type": "thinking",
        "thinking": "I need to inspect the steering files first.",
    }
    assert assistant_content[1]["type"] == "tool_use"
    assert payload["messages"][2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "commit output",
    }


@pytest.mark.parametrize(
    ("reasoning_effort", "expected_thinking_type"),
    [("none", "disabled"), ("low", "enabled"), ("high", "enabled")],
)
def test_payload_maps_reasoning_effort_to_qwen_thinking_mode(
    reasoning_effort: str,
    expected_thinking_type: str,
) -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.8-max-preview",
        messages=[ChatMessage(role="user", content="hello")],
        reasoning_effort=reasoning_effort,
    )

    payload = backend._prepare_anthropic_payload(
        request,
        [ChatMessage(role="user", content="hello")],
        "qwen3.8-max-preview",
        None,
    )

    assert "reasoning_effort" not in payload
    assert payload["thinking"] == {"type": expected_thinking_type}


@pytest.mark.asyncio
async def test_stream_completion_sends_extended_thinking_beta_header() -> None:
    backend = _backend()
    backend.api_key = "env-secret"
    backend.auth_header_name = "x-api-key"
    backend.anthropic_api_base_url = ALIBABA_TOKEN_PLAN_INTL_DEFAULT_BASE_URL
    response = MagicMock()
    response.status_code = 200
    response.headers = httpx.Headers()
    response.aclose = AsyncMock()

    async def response_lines():
        yield 'data: {"type":"message_stop"}'

    response.aiter_lines = response_lines
    request = CanonicalChatRequest(
        model="qwen3.8-max-preview",
        messages=[ChatMessage(role="user", content="hello")],
        reasoning_effort="high",
        stream=True,
        extra_body={"anthropic_beta": "custom-beta"},
    )

    with patch.object(backend, "_capture_http_client") as capture_client:
        capture_client.send = AsyncMock(return_value=response)
        chunks = [chunk async for chunk in backend.stream_completion(request)]

    assert chunks == ['data: {"type":"message_stop"}']
    assert capture_client.send.await_args is not None
    upstream_request = capture_client.send.await_args.args[0]
    assert (
        upstream_request.headers["anthropic-beta"]
        == "interleaved-thinking-2025-05-14,custom-beta"
    )
    assert "anthropic_beta" not in json.loads(upstream_request.content)
    await backend.client.aclose()


@pytest.mark.asyncio
async def test_stream_completion_omits_beta_header_when_thinking_disabled() -> None:
    backend = _backend()
    backend.api_key = "env-secret"
    backend.auth_header_name = "x-api-key"
    backend.anthropic_api_base_url = ALIBABA_TOKEN_PLAN_INTL_DEFAULT_BASE_URL
    response = MagicMock()
    response.status_code = 200
    response.headers = httpx.Headers()
    response.aclose = AsyncMock()

    async def response_lines():
        yield 'data: {"type":"message_stop"}'

    response.aiter_lines = response_lines
    request = CanonicalChatRequest(
        model="qwen3.8-max-preview",
        messages=[ChatMessage(role="user", content="hello")],
        reasoning_effort="none",
        stream=True,
    )

    with patch.object(backend, "_capture_http_client") as capture_client:
        capture_client.send = AsyncMock(return_value=response)
        chunks = [chunk async for chunk in backend.stream_completion(request)]

    assert chunks == ['data: {"type":"message_stop"}']
    assert capture_client.send.await_args is not None
    upstream_request = capture_client.send.await_args.args[0]
    assert "anthropic-beta" not in upstream_request.headers
    await backend.client.aclose()


@pytest.mark.asyncio
async def test_chat_completions_strips_alibaba_provider_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALIBABA_TOKEN_PLAN_API_KEY", "env-secret")
    backend = _backend()
    request = ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="alibaba/qwen3.8-max-preview",
            messages=[ChatMessage(role="user", content="hello")],
            extra_body={"model": "alibaba/qwen3.8-max-preview"},
        ),
        processed_messages=[ChatMessage(role="user", content="hello")],
        effective_model="alibaba/qwen3.8-max-preview",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
    )

    with patch.object(
        AnthropicBackend,
        "_chat_completions_canonical",
        new_callable=AsyncMock,
    ) as parent_chat:
        await backend._chat_completions_canonical(request)

    assert parent_chat.await_args is not None
    normalized_request = parent_chat.await_args.args[0]
    assert normalized_request.effective_model == "qwen3.8-max-preview"
    assert normalized_request.request.model == "qwen3.8-max-preview"
    assert normalized_request.request.extra_body == {"model": "qwen3.8-max-preview"}
    await backend.client.aclose()


def test_backend_is_registered() -> None:
    assert (
        backend_registry.get_backend_factory("alibaba-token-plan-intl")
        is AlibabaTokenPlanIntlBackend
    )
