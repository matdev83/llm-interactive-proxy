"""Tests for the opencode-go backend connector."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import MagicMock

import httpx
import pytest

opencode_go_module = pytest.importorskip("src.connectors.opencode_go")

from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.core.common.exceptions import RoutingError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService

OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
CURATED_OPENAI_MODELS = [
    "glm-5",
    "glm-5.1",
    "kimi-k2.5",
    "mimo-v2-pro",
    "mimo-v2-omni",
]
CURATED_ANTHROPIC_MODELS = [
    "minimax-m2.5",
    "minimax-m2.7",
]
CURATED_MODELS = CURATED_OPENAI_MODELS + CURATED_ANTHROPIC_MODELS


class RequestRecorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.rstrip("/")

        if path.endswith("/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": model} for model in CURATED_MODELS]},
            )

        if path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-opencode-go",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        if path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "id": "msg-opencode-go",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                },
            )

        raise AssertionError(f"Unexpected request URL: {request.method} {request.url}")


async def _make_backend(
    client: httpx.AsyncClient,
    *,
    overrides: dict[str, str] | None = None,
) -> Any:
    config = MagicMock(spec=AppConfig)
    config.streaming_yield_interval = 0.0
    config.backends = MagicMock()

    backend = opencode_go_module.OpencodeGoBackend(
        client=client,
        config=config,
        translation_service=TranslationService(),
    )

    await backend.initialize(
        api_key="test-api-key",
        api_base_url=OPENCODE_GO_BASE_URL,
        openai_api_base_url=OPENCODE_GO_BASE_URL,
        anthropic_api_base_url=OPENCODE_GO_BASE_URL,
        key_name="opencode-go",
        model_protocol_overrides=dict(overrides or {}),
    )

    disable_health_check = getattr(backend, "disable_health_check", None)
    if callable(disable_health_check):
        disable_health_check()
    elif hasattr(backend, "_health_check_enabled"):
        backend._health_check_enabled = False

    return backend


def _make_request(
    model: str,
    *,
    stream: bool = False,
) -> ConnectorChatCompletionsRequest:
    canonical_request = CanonicalChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
        max_tokens=16,
        stream=stream,
    )
    return ConnectorChatCompletionsRequest(
        request=canonical_request,
        processed_messages=[ChatMessage(role="user", content="hello")],
        effective_model=model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="test-request-id",
            session_id="test-session-id",
            client_host="127.0.0.1",
            extensions={},
        ),
        options={},
    )


def _posted_json(requests: list[httpx.Request], path_suffix: str) -> dict[str, Any]:
    for request in requests:
        if request.method == "POST" and request.url.path.endswith(path_suffix):
            return cast(dict[str, Any], json.loads(request.content.decode("utf-8")))
    raise AssertionError(f"No POST request found for suffix {path_suffix!r}")


@pytest.mark.asyncio
async def test_openai_path_routes_curated_openai_models_to_chat_completions() -> None:
    recorder = RequestRecorder()
    transport = httpx.MockTransport(recorder)

    async with httpx.AsyncClient(transport=transport) as client:
        backend = await _make_backend(client)

        await backend.chat_completions(_make_request("opencode-go:glm-5.1"))

    assert any(
        request.method == "POST" and request.url.path.endswith("/chat/completions")
        for request in recorder.requests
    )
    assert not any(
        request.method == "POST" and request.url.path.endswith("/messages")
        for request in recorder.requests
    )

    payload = _posted_json(recorder.requests, "/chat/completions")
    assert payload["model"] == "glm-5.1"


@pytest.mark.asyncio
async def test_anthropic_path_routes_curated_anthropic_models_to_messages() -> None:
    recorder = RequestRecorder()
    transport = httpx.MockTransport(recorder)

    async with httpx.AsyncClient(transport=transport) as client:
        backend = await _make_backend(client)

        await backend.chat_completions(_make_request("opencode-go:minimax-m2.7"))

    assert any(
        request.method == "POST" and request.url.path.endswith("/messages")
        for request in recorder.requests
    )
    assert not any(
        request.method == "POST" and request.url.path.endswith("/chat/completions")
        for request in recorder.requests
    )

    payload = _posted_json(recorder.requests, "/messages")
    assert payload["model"] == "minimax-m2.7"


@pytest.mark.asyncio
async def test_model_protocol_overrides_can_redirect_unknown_models() -> None:
    recorder = RequestRecorder()
    transport = httpx.MockTransport(recorder)

    async with httpx.AsyncClient(transport=transport) as client:
        backend = await _make_backend(
            client,
            overrides={"custom-openai-model": "openai"},
        )

        await backend.chat_completions(_make_request("opencode-go:custom-openai-model"))

    payload = _posted_json(recorder.requests, "/chat/completions")
    assert payload["model"] == "custom-openai-model"


@pytest.mark.asyncio
async def test_model_protocol_overrides_can_redirect_to_anthropic() -> None:
    recorder = RequestRecorder()
    transport = httpx.MockTransport(recorder)

    async with httpx.AsyncClient(transport=transport) as client:
        backend = await _make_backend(
            client,
            overrides={"custom-anthropic-model": "anthropic"},
        )

        await backend.chat_completions(
            _make_request("opencode-go:custom-anthropic-model")
        )

    payload = _posted_json(recorder.requests, "/messages")
    assert payload["model"] == "custom-anthropic-model"


@pytest.mark.asyncio
async def test_unknown_model_is_rejected_deterministically() -> None:
    recorder = RequestRecorder()
    transport = httpx.MockTransport(recorder)

    async with httpx.AsyncClient(transport=transport) as client:
        backend = await _make_backend(client)

        with pytest.raises(RoutingError) as exc_info:
            await backend.chat_completions(_make_request("opencode-go:does-not-exist"))

    exc = exc_info.value
    assert exc.details.get("code") == "unknown_model"
    supported_models = exc.details.get("supported_models")
    assert isinstance(supported_models, list)
    assert "opencode-go/glm-5" in supported_models
    assert "opencode-go/minimax-m2.7" in supported_models


@pytest.mark.asyncio
async def test_available_models_are_canonically_prefixed() -> None:
    recorder = RequestRecorder()
    transport = httpx.MockTransport(recorder)

    async with httpx.AsyncClient(transport=transport) as client:
        backend = await _make_backend(
            client,
            overrides={"custom-openai-model": "openai"},
        )

        models = backend.get_available_models()
        async_models = await backend.get_available_models_async()

    expected = [f"opencode-go/{model}" for model in CURATED_MODELS]
    assert models[: len(expected)] == expected
    assert async_models[: len(expected)] == expected
    assert "opencode-go/custom-openai-model" in models
    assert "opencode-go/custom-openai-model" in async_models
