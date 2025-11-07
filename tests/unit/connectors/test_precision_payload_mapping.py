from __future__ import annotations

from typing import Any

import httpx
import pytest
from src.connectors.anthropic import AnthropicBackend
from src.connectors.gemini import GeminiBackend
from src.connectors.gemini_cloud_project import GeminiCloudProjectConnector
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
from src.connectors.openai import OpenAIConnector
from src.connectors.openrouter import OpenRouterBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService


def _messages() -> list[Any]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_openai_payload_contains_temperature_and_top_p(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = AppConfig()
    client = httpx.AsyncClient()
    connector = OpenAIConnector(client, cfg, translation_service=TranslationService())
    connector.api_key = "test-api-key"  # Add API key to avoid authentication error
    req = ChatRequest(model="gpt-4", messages=_messages(), temperature=0.12, top_p=0.34)

    captured_payload = {}

    async def fake_post(url: str, json: dict, headers: dict) -> httpx.Response:
        captured_payload.update(json)
        return httpx.Response(
            200, json={"id": "1", "choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr(client, "post", fake_post)

    await connector.chat_completions(req, req.messages, req.model)

    assert captured_payload.get("temperature") == 0.12
    assert captured_payload.get("top_p") == 0.34


@pytest.mark.asyncio
async def test_openai_warns_for_unsupported_penalties(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = AppConfig()
    client = httpx.AsyncClient()
    connector = OpenAIConnector(client, cfg, translation_service=TranslationService())
    connector.api_key = "test-api-key"
    req = ChatRequest(
        model="gpt-4",
        messages=_messages(),
        repetition_penalty=1.1,
        min_p=0.05,
    )

    captured_payload: dict[str, Any] = {}

    async def fake_post(url: str, json: dict, headers: dict) -> httpx.Response:
        captured_payload.update(json)
        return httpx.Response(
            200, json={"id": "1", "choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr(client, "post", fake_post)
    caplog.set_level("WARNING")

    await connector.chat_completions(req, req.messages, req.model)

    assert "does not support the 'repetition_penalty'" in caplog.text
    assert "does not support the 'min_p'" in caplog.text
    assert "repetition_penalty" not in captured_payload
    assert "min_p" not in captured_payload


@pytest.mark.asyncio
async def test_openai_payload_uses_processed_messages_with_list_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = AppConfig()
    client = httpx.AsyncClient()
    connector = OpenAIConnector(client, cfg, translation_service=TranslationService())
    connector.api_key = "test-api-key"
    req = ChatRequest(model="gpt-4", messages=_messages())

    processed_messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "World"},
            ],
        }
    ]

    captured_payload: dict[str, Any] = {}

    async def fake_post(url: str, json: dict, headers: dict) -> httpx.Response:
        captured_payload.update(json)
        return httpx.Response(
            200, json={"id": "1", "choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr(client, "post", fake_post)

    await connector.chat_completions(req, processed_messages, req.model)

    assert captured_payload.get("messages") == processed_messages


@pytest.mark.asyncio
async def test_openrouter_payload_contains_temperature_and_top_p(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = AppConfig()
    client = httpx.AsyncClient()
    connector = OpenRouterBackend(client, cfg, translation_service=TranslationService())
    connector.api_key = "test-api-key"  # Add API key to avoid authentication error
    req = ChatRequest(
        model="openrouter:gpt-4",
        messages=_messages(),
        temperature=0.2,
        top_p=0.5,
        repetition_penalty=1.01,
        min_p=0.15,
    )

    captured_payload = {}

    async def fake_post(url: str, json: dict, headers: dict) -> httpx.Response:
        captured_payload.update(json)
        return httpx.Response(
            200, json={"id": "1", "choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr(client, "post", fake_post)

    await connector.chat_completions(req, req.messages, "gpt-4")

    assert captured_payload.get("temperature") == 0.2
    assert captured_payload.get("top_p") == 0.5
    assert captured_payload.get("repetition_penalty") == 1.01
    assert captured_payload.get("min_p") == 0.15


@pytest.mark.asyncio
async def test_anthropic_payload_contains_temperature_and_top_p(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = AppConfig()
    client = httpx.AsyncClient()
    backend = AnthropicBackend(client, cfg, TranslationService())

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

    monkeypatch.setattr(client, "post", fake_post)

    req = ChatRequest(
        model="claude-3",
        messages=_messages(),
        temperature=0.25,
        top_p=0.6,
        repetition_penalty=1.05,
        min_p=0.2,
    )
    caplog.set_level("WARNING")
    await backend.chat_completions(req, req.messages, req.model, api_key="test-key")
    payload = captured.get("payload", {})
    assert payload.get("temperature") == 0.25
    assert payload.get("top_p") == 0.6
    assert "repetition_penalty" not in payload
    assert "min_p" not in payload
    assert "repetition_penalty" in caplog.text
    assert "min_p" in caplog.text


def test_gemini_public_generation_config_clamping_and_topk() -> None:
    cfg = AppConfig()
    backend = GeminiBackend(
        httpx.AsyncClient(), cfg, translation_service=TranslationService()
    )
    payload: dict[str, Any] = {}
    req = ChatRequest(
        model="gemini-pro", messages=_messages(), temperature=1.5, top_p=0.4, top_k=50
    )
    backend._apply_generation_config(payload, req)
    gc = payload.get("generationConfig", {})
    assert gc.get("temperature") == 1.0  # clamped
    assert gc.get("topP") == 0.4
    assert gc.get("topK") == 50


def test_gemini_generation_config_warns_for_penalties(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = AppConfig()
    backend = GeminiBackend(
        httpx.AsyncClient(), cfg, translation_service=TranslationService()
    )
    payload: dict[str, Any] = {}
    req = ChatRequest(
        model="gemini-pro",
        messages=_messages(),
        repetition_penalty=1.05,
        min_p=0.22,
    )
    caplog.set_level("WARNING")
    backend._apply_generation_config(payload, req)
    gc = payload.get("generationConfig", {})
    assert "repetitionPenalty" not in gc
    assert "minP" not in gc
    assert "repetition_penalty" in caplog.text
    assert "min_p" in caplog.text


def test_gemini_oauth_personal_builds_topk(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = AppConfig()
    backend = GeminiOAuthPlanConnector(
        httpx.AsyncClient(), cfg, translation_service=TranslationService()
    )

    class _Req:
        temperature = 0.22
        top_p = 0.55
        top_k = 33
        max_tokens = 777
        repetition_penalty = 1.02
        min_p = 0.18

    caplog.set_level("WARNING")
    gc = backend._build_generation_config(_Req())
    assert gc["temperature"] == pytest.approx(0.22)
    assert gc["topP"] == pytest.approx(0.55)
    assert gc["topK"] == 33
    assert "repetition_penalty" in caplog.text
    assert "min_p" in caplog.text


def test_gemini_cloud_project_builds_topk(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = AppConfig()
    # Minimal init (project id may be None for this isolated helper test)
    backend = GeminiCloudProjectConnector(
        httpx.AsyncClient(),
        cfg,
        translation_service=TranslationService(),
        gcp_project_id="test-proj",
    )

    class _Req:
        temperature = 0.3
        top_p = 0.77
        top_k = 21
        max_tokens = 512
        repetition_penalty = 1.04
        min_p = 0.12

    caplog.set_level("WARNING")
    gc = backend._build_generation_config(_Req())
    assert gc["temperature"] == pytest.approx(0.3)
    assert gc["topP"] == pytest.approx(0.77)
    assert gc["topK"] == 21
    assert "repetition_penalty" in caplog.text
    assert "min_p" in caplog.text
