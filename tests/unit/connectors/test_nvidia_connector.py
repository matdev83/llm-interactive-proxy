from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.nvidia import NVIDIA_DEFAULT_BASE_URL, NvidiaConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


@pytest.mark.asyncio
async def test_initialize_uses_nvidia_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nvidia connector should read NVIDIA_API_KEY when no key is provided."""
    monkeypatch.setenv("NVIDIA_API_KEY", "env-nvidia-key")

    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": [{"id": "meta/llama3-70b"}]}
    response.status_code = 200
    client.get.return_value = response

    connector = NvidiaConnector(client, config=AppConfig())
    await connector.initialize()

    assert connector.api_key == "env-nvidia-key"
    assert connector.available_models == ["meta/llama3-70b"]
    await_args = client.get.await_args
    assert await_args.args[0] == f"{NVIDIA_DEFAULT_BASE_URL}/models"
    headers = await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer env-nvidia-key"
    assert "x-llmproxy-loop-guard" in headers


@pytest.mark.asyncio
async def test_initialize_strips_whitespace_from_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "  trimmed-key  ")

    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": []}
    response.status_code = 200
    client.get.return_value = response

    connector = NvidiaConnector(client, config=AppConfig())
    await connector.initialize()

    assert connector.api_key == "trimmed-key"
    headers = client.get.await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer trimmed-key"


@pytest.mark.asyncio
async def test_initialize_strips_bearer_prefix_from_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "Bearer inner-key")

    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": []}
    response.status_code = 200
    client.get.return_value = response

    connector = NvidiaConnector(client, config=AppConfig())
    await connector.initialize()

    assert connector.api_key == "inner-key"
    assert (
        client.get.await_args.kwargs["headers"]["Authorization"] == "Bearer inner-key"
    )


@pytest.mark.asyncio
async def test_initialize_prefers_explicit_api_key_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit api_key in initialize kwargs must win over NVIDIA_API_KEY."""
    monkeypatch.setenv("NVIDIA_API_KEY", "env-nvidia-key")

    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": [{"id": "meta/llama3-8b"}]}
    response.status_code = 200
    client.get.return_value = response

    connector = NvidiaConnector(client, config=AppConfig())
    await connector.initialize(api_key="  explicit-key  ")

    assert connector.api_key == "explicit-key"
    await_args = client.get.await_args
    assert await_args.kwargs["headers"]["Authorization"] == "Bearer explicit-key"


@pytest.mark.asyncio
async def test_initialize_respects_api_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api_base_url in kwargs should override the default hosted integrator URL."""
    monkeypatch.setenv("NVIDIA_API_KEY", "k")

    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": []}
    response.status_code = 200
    client.get.return_value = response

    connector = NvidiaConnector(client, config=AppConfig())
    await connector.initialize(api_base_url="https://self-hosted.example/v1")

    assert connector.api_base_url == "https://self-hosted.example/v1"
    await_args = client.get.await_args
    assert await_args.args[0] == "https://self-hosted.example/v1/models"


@pytest.mark.asyncio
async def test_initialize_empty_models_when_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without API key and without static models, discovery stays empty (Req 1.3)."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    client = AsyncMock()
    connector = NvidiaConnector(client, config=AppConfig())
    await connector.initialize()

    assert connector.api_key is None
    assert connector.available_models == []
    client.get.assert_not_awaited()


def test_get_headers_bearer_shape() -> None:
    """Authorization header matches other Bearer API-key OpenAI-style backends."""
    client = AsyncMock()
    connector = NvidiaConnector(client, config=AppConfig())
    connector.api_key = "test-nvidia-secret"

    headers = connector.get_headers(identity=None)

    assert headers["Authorization"] == "Bearer test-nvidia-secret"
    assert "x-llmproxy-loop-guard" in headers


@pytest.mark.asyncio
async def test_list_models_respects_override() -> None:
    """list_models should allow overriding the base URL when needed."""
    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": []}
    response.status_code = 200
    client.get.return_value = response

    connector = NvidiaConnector(client, config=AppConfig())
    connector.api_key = "provided-key"

    await connector.list_models(api_base_url="https://alt.api")

    await_args = client.get.await_args
    assert await_args.args[0] == "https://alt.api/models"
    headers = await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer provided-key"


@pytest.mark.asyncio
async def test_prepare_payload_maps_max_completion_tokens_to_max_tokens() -> None:
    """NIM integrator rejects max_completion_tokens (strict body schema)."""
    client = AsyncMock()
    connector = NvidiaConnector(
        client, AppConfig(), translation_service=TranslationService()
    )
    connector.api_key = "k"
    req = CanonicalChatRequest(
        model="meta/llama-3.2-1b-instruct",
        messages=[ChatMessage(role="user", content="hi")],
        max_completion_tokens=42,
    )
    payload = await connector._prepare_payload(req, list(req.messages), req.model, None)
    assert "max_completion_tokens" not in payload
    assert payload.get("max_tokens") == 42


@pytest.mark.asyncio
async def test_prepare_payload_keeps_max_tokens_when_both_token_limits_set() -> None:
    client = AsyncMock()
    connector = NvidiaConnector(
        client, AppConfig(), translation_service=TranslationService()
    )
    connector.api_key = "k"
    req = CanonicalChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="x")],
        max_tokens=10,
        max_completion_tokens=99,
    )
    payload = await connector._prepare_payload(req, list(req.messages), req.model, None)
    assert "max_completion_tokens" not in payload
    assert payload.get("max_tokens") == 10


@pytest.mark.asyncio
async def test_connector_uses_dedicated_http11_client_when_httpx_real() -> None:
    """NVIDIA traffic must not use the shared HTTP/2 pool (integrator disconnects)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "meta/x"}]})

    transport = httpx.MockTransport(handler)
    shared = httpx.AsyncClient(http2=True, transport=transport, trust_env=False)
    connector = NvidiaConnector(shared, AppConfig())
    try:
        await connector.initialize(api_key="k")
        assert connector.client is not shared
        assert connector._nvidia_http11_client is connector.client
        assert not connector.client.is_closed
    finally:
        await connector.close()
        await shared.aclose()


@pytest.mark.asyncio
async def test_prepare_payload_drops_stream_options_for_nim_schema() -> None:
    """Hosted NIM body schema often rejects unknown keys such as ``stream_options``."""
    client = AsyncMock()
    connector = NvidiaConnector(
        client, AppConfig(), translation_service=TranslationService()
    )
    connector.api_key = "k"
    req = CanonicalChatRequest(
        model="moonshotai/kimi-k2.5",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    payload = await connector._prepare_payload(req, list(req.messages), req.model, None)
    assert payload.get("stream") is True
    assert "stream_options" not in payload
