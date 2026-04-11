from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest
from src.connectors.anthropic import AnthropicBackend
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.gemini import GeminiBackend
from src.connectors.openai import (
    _LLM_PROXY_STREAM_HEADERS_KEY,
    _LLM_PROXY_STREAM_URL_KEY,
    OpenAIConnector,
)
from src.connectors.zai import ZAIConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


class CborWireCaptureService:
    def __init__(self) -> None:
        self.outbound_requests: list[dict[str, Any]] = []
        self.inbound_responses: list[dict[str, Any]] = []

    def enabled(self) -> bool:
        return True

    async def capture_outbound_request(self, **kwargs: Any) -> None:
        self.outbound_requests.append(kwargs)

    async def capture_inbound_response(self, **kwargs: Any) -> None:
        self.inbound_responses.append(kwargs)


def _connector_context() -> ConnectorRequestContext:
    return ConnectorRequestContext(
        request_id="req-boundary-capture",
        session_id="sess-boundary-capture",
        client_host="127.0.0.1",
        extensions={},
    )


def _canonical_request(
    request: CanonicalChatRequest,
    *,
    effective_model: str,
) -> ConnectorChatCompletionsRequest:
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=list(request.messages),
        effective_model=effective_model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=_connector_context(),
        options={},
    )


def _json_body_from_http_message(message: bytes) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads(message.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
    )


def _openai_response_payload(model: str, content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-boundary",
        "object": "chat.completion",
        "created": 1234567890,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "total_tokens": 5,
        },
    }


@pytest.mark.asyncio
async def test_openai_boundary_capture_uses_final_clean_payload_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire_capture = CborWireCaptureService()
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture._resolve_wire_capture",
        lambda: wire_capture,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            request=request,
            json=_openai_response_payload("gpt-4o-mini", "openai boundary capture ok"),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    ) as client:
        connector = OpenAIConnector(
            client=client,
            config=AppConfig(),
            translation_service=TranslationService(),
        )
        connector.api_key = "test-openai-key"
        connector.api_base_url = "https://api.openai.com/v1"
        connector.disable_health_check()

        envelope = await connector.chat_completions(
            _canonical_request(
                CanonicalChatRequest(
                    model="gpt-4o-mini",
                    messages=[ChatMessage(role="user", content="hello")],
                    stream=False,
                    extra_body={
                        "custom_flag": "preserve-me",
                        _LLM_PROXY_STREAM_URL_KEY: "https://should-not-leak.example",
                        _LLM_PROXY_STREAM_HEADERS_KEY: {"X-Leak": "no"},
                    },
                ),
                effective_model="gpt-4o-mini",
            )
        )

    outbound_payload = _json_body_from_http_message(
        wire_capture.outbound_requests[0]["request_payload"]
    )
    inbound_payload = _json_body_from_http_message(
        wire_capture.inbound_responses[0]["response_content"]
    )
    envelope_content = cast(dict[str, Any], envelope.content)

    assert (
        envelope_content["choices"][0]["message"]["content"]
        == "openai boundary capture ok"
    )
    assert wire_capture.outbound_requests[0]["backend"] == "openai"
    assert wire_capture.inbound_responses[0]["backend"] == "openai"
    assert outbound_payload["custom_flag"] == "preserve-me"
    assert _LLM_PROXY_STREAM_URL_KEY not in outbound_payload
    assert _LLM_PROXY_STREAM_HEADERS_KEY not in outbound_payload
    assert outbound_payload["messages"][0]["content"] == "hello"
    assert (
        inbound_payload["choices"][0]["message"]["content"]
        == "openai boundary capture ok"
    )


@pytest.mark.asyncio
async def test_anthropic_boundary_capture_uses_final_payload_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire_capture = CborWireCaptureService()
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture._resolve_wire_capture",
        lambda: wire_capture,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "msg_boundary",
                "type": "message",
                "role": "assistant",
                "model": "claude-3-haiku-20240307",
                "content": [{"type": "text", "text": "anthropic boundary capture ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    ) as client:
        connector = AnthropicBackend(
            client=client,
            config=AppConfig(),
            translation_service=TranslationService(),
        )
        connector.api_key = "test-anthropic-key"
        connector.anthropic_api_base_url = "https://api.anthropic.com/v1"

        envelope = await connector.chat_completions(
            _canonical_request(
                CanonicalChatRequest(
                    model="claude-3-haiku-20240307",
                    messages=[ChatMessage(role="user", content="hello")],
                    stream=False,
                    user="anthropic-user",
                    extra_body={
                        "session_id": "internal-only",
                        "backend_type": "anthropic",
                        "custom_flag": "preserve-me",
                    },
                ),
                effective_model="claude-3-haiku-20240307",
            )
        )

    outbound_payload = _json_body_from_http_message(
        wire_capture.outbound_requests[0]["request_payload"]
    )
    inbound_payload = _json_body_from_http_message(
        wire_capture.inbound_responses[0]["response_content"]
    )
    envelope_content = cast(dict[str, Any], envelope.content)

    assert (
        envelope_content["choices"][0]["message"]["content"]
        == "anthropic boundary capture ok"
    )
    assert wire_capture.outbound_requests[0]["backend"] == "anthropic"
    assert outbound_payload["custom_flag"] == "preserve-me"
    assert "session_id" not in outbound_payload
    assert "backend_type" not in outbound_payload
    assert outbound_payload["metadata"]["user_id"] == "anthropic-user"
    assert outbound_payload["messages"][0]["content"] == "hello"
    assert inbound_payload["content"][0]["text"] == "anthropic boundary capture ok"


@pytest.mark.asyncio
async def test_gemini_boundary_capture_uses_final_provider_payload_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire_capture = CborWireCaptureService()
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture._resolve_wire_capture",
        lambda: wire_capture,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models/gemini-2.5-pro:generateContent")
        return httpx.Response(
            200,
            request=request,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "gemini boundary capture ok"}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 5,
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    ) as client:
        connector = GeminiBackend(
            client=client,
            config=AppConfig(),
            translation_service=TranslationService(),
        )
        connector.api_key = "test-gemini-key"
        connector.key_name = "x-goog-api-key"
        connector.gemini_api_base_url = "https://generativelanguage.googleapis.com"

        envelope = await connector.chat_completions(
            _canonical_request(
                CanonicalChatRequest(
                    model="gemini-2.5-pro",
                    messages=[ChatMessage(role="user", content="hello")],
                    stream=False,
                    temperature=0.25,
                    extra_body={
                        "generationConfig": {"candidateCount": 1},
                        "customFlag": "preserve-me",
                    },
                ),
                effective_model="gemini-2.5-pro",
            )
        )

    outbound_payload = _json_body_from_http_message(
        wire_capture.outbound_requests[0]["request_payload"]
    )
    inbound_payload = _json_body_from_http_message(
        wire_capture.inbound_responses[0]["response_content"]
    )
    envelope_content = cast(dict[str, Any], envelope.content)

    assert (
        envelope_content["choices"][0]["message"]["content"]
        == "gemini boundary capture ok"
    )
    assert wire_capture.outbound_requests[0]["backend"] == "gemini"
    assert outbound_payload["customFlag"] == "preserve-me"
    assert outbound_payload["contents"][0]["parts"][0]["text"] == "hello"
    assert outbound_payload["generationConfig"]["temperature"] == pytest.approx(0.25)
    assert outbound_payload["generationConfig"]["candidateCount"] == 1
    assert "generation_config" not in outbound_payload
    assert (
        inbound_payload["candidates"][0]["content"]["parts"][0]["text"]
        == "gemini boundary capture ok"
    )


@pytest.mark.asyncio
async def test_zai_boundary_capture_uses_final_provider_payload_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire_capture = CborWireCaptureService()
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture._resolve_wire_capture",
        lambda: wire_capture,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/paas/v4/chat/completions"
        return httpx.Response(
            200,
            request=request,
            json=_openai_response_payload("glm-4.5", "zai boundary capture ok"),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    ) as client:
        connector = ZAIConnector(
            client=client,
            config=AppConfig(),
            translation_service=TranslationService(),
        )
        connector.api_key = "test-zai-key"
        connector.disable_health_check()

        envelope = await connector.chat_completions(
            _canonical_request(
                CanonicalChatRequest(
                    model="glm-4.5",
                    messages=[ChatMessage(role="user", content="hello")],
                    stream=False,
                    max_tokens=0,
                    reasoning_effort="high",
                    extra_body={
                        "reasoning": {"type": "supported-upstream-not-zai"},
                        "top_p": 0.8,
                        "top_k": 7,
                    },
                ),
                effective_model="glm-4.5",
            )
        )

    outbound_payload = _json_body_from_http_message(
        wire_capture.outbound_requests[0]["request_payload"]
    )
    inbound_payload = _json_body_from_http_message(
        wire_capture.inbound_responses[0]["response_content"]
    )
    envelope_content = cast(dict[str, Any], envelope.content)

    assert (
        envelope_content["choices"][0]["message"]["content"]
        == "zai boundary capture ok"
    )
    assert wire_capture.outbound_requests[0]["backend"] == "zai"
    assert outbound_payload["top_p"] == pytest.approx(0.8)
    assert outbound_payload["top_k"] == 7
    assert outbound_payload["max_tokens"] == 200000
    assert "reasoning" not in outbound_payload
    assert "reasoning_effort" not in outbound_payload
    assert (
        inbound_payload["choices"][0]["message"]["content"] == "zai boundary capture ok"
    )
