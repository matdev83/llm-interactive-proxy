from __future__ import annotations

from typing import Any

import httpx
import pytest
from src.connectors.anthropic import AnthropicBackend
from src.connectors.gemini import GeminiBackend
from src.connectors.gemini_cloud_project import GeminiCloudProjectConnector
from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector
from src.connectors.openai import OpenAIConnector
from src.connectors.openrouter import OpenRouterBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest


def _messages() -> list[Any]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_openai_payload_contains_temperature_and_top_p() -> None:
    cfg = AppConfig()
    connector = OpenAIConnector(httpx.AsyncClient(), cfg)
    req = ChatRequest(model="gpt-4", messages=_messages(), temperature=0.12, top_p=0.34)
    payload = connector._prepare_payload(
        req, [m.model_dump() for m in req.messages], req.model
    )
    assert payload.get("temperature") == 0.12
    assert payload.get("top_p") == 0.34


@pytest.mark.asyncio
async def test_openrouter_payload_contains_temperature_and_top_p() -> None:
    cfg = AppConfig()
    connector = OpenRouterBackend(httpx.AsyncClient(), cfg)  # type: ignore[arg-type]
    req = ChatRequest(
        model="openrouter:gpt-4", messages=_messages(), temperature=0.2, top_p=0.5
    )
    payload = connector._prepare_payload(
        req, [m.model_dump() for m in req.messages], "gpt-4"
    )
    assert payload.get("temperature") == 0.2
    assert payload.get("top_p") == 0.5


@pytest.mark.asyncio
async def test_anthropic_payload_contains_temperature_and_top_p(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = AppConfig()
    backend = AnthropicBackend(httpx.AsyncClient(), cfg)

    captured: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "id": "anth-1",
                "model": "claude-3",
                "content": [{"type": "text", "text": "ok"}],
            }

        def raise_for_status(self) -> None:  # pragma: no cover - trivial
            return None

        @property
        def headers(self) -> dict[str, str]:  # pragma: no cover - trivial
            return {}

    async def fake_post(url: str, json: dict, headers: dict) -> Any:  # type: ignore[override]
        captured["payload"] = json
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(backend.client, "post", fake_post)

    req = ChatRequest(
        model="claude-3", messages=_messages(), temperature=0.25, top_p=0.6
    )
    await backend.chat_completions(req, req.messages, req.model, api_key="test-key")
    payload = captured.get("payload", {})
    assert payload.get("temperature") == 0.25
    assert payload.get("top_p") == 0.6


def test_gemini_public_generation_config_clamping_and_topk() -> None:
    cfg = AppConfig()
    backend = GeminiBackend(httpx.AsyncClient(), cfg)
    payload: dict[str, Any] = {}
    req = ChatRequest(
        model="gemini-pro", messages=_messages(), temperature=1.5, top_p=0.4, top_k=50
    )
    backend._apply_generation_config(payload, req)
    gc = payload.get("generationConfig", {})
    assert gc.get("temperature") == 1.0  # clamped
    assert gc.get("topP") == 0.4
    assert gc.get("topK") == 50


def test_gemini_oauth_personal_builds_topk() -> None:
    cfg = AppConfig()
    backend = GeminiOAuthPersonalConnector(httpx.AsyncClient(), cfg)  # type: ignore[arg-type]

    class _Req:
        temperature = 0.22
        top_p = 0.55
        top_k = 33
        max_tokens = 777

    gc = backend._build_generation_config(_Req())
    assert gc["temperature"] == pytest.approx(0.22)
    assert gc["topP"] == pytest.approx(0.55)
    assert gc["topK"] == 33


def test_gemini_cloud_project_builds_topk() -> None:
    cfg = AppConfig()
    # Minimal init (project id may be None for this isolated helper test)
    backend = GeminiCloudProjectConnector(httpx.AsyncClient(), cfg, gcp_project_id="test-proj")  # type: ignore[arg-type]

    class _Req:
        temperature = 0.3
        top_p = 0.77
        top_k = 21
        max_tokens = 512

    gc = backend._build_generation_config(_Req())
    assert gc["temperature"] == pytest.approx(0.3)
    assert gc["topP"] == pytest.approx(0.77)
    assert gc["topK"] == 21
