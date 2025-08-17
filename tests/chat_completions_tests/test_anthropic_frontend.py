from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
    LoggingConfig,
    SessionConfig,
)


@pytest.fixture()
def anthropic_client():
    """Create TestClient with config patched for Anthropic."""
    with (
        patch("src.core.config.app_config.load_config") as mock_cfg,
        patch(
            "src.connectors.anthropic.AnthropicBackend.get_available_models",
            return_value=["claude-3-haiku-20240229"],
        ),
    ):
        # Create a proper AppConfig object
        config = AppConfig()
        config.auth = AuthConfig(disable_auth=False, api_keys=["test-proxy-key"])
        config.proxy_timeout = 10
        config.session = SessionConfig(default_interactive_mode=False)
        config.command_prefix = "!/"
        config.backends = BackendSettings()
        config.backends.anthropic = BackendConfig(
            api_key=["ant-key"], api_url="https://api.anthropic.com/v1"
        )
        config.backends.default_backend = "anthropic"
        config.logging = LoggingConfig()

        mock_cfg.return_value = config
        app = build_app()
        with TestClient(app) as client:
            yield client


def _dummy_anthropic_response(text: str = "Test reply") -> dict:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-3-haiku-20240229",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 5, "output_tokens": 7},
    }


# ------------------------------------------------------------
# Non-streaming
# ------------------------------------------------------------


def test_anthropic_messages_non_streaming_frontend(anthropic_client):
    with patch(
        "src.connectors.anthropic.AnthropicBackend.chat_completions",
        new_callable=AsyncMock,
    ) as mock_chat:
        mock_chat.return_value = (_dummy_anthropic_response(), {})

        res = anthropic_client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer test-proxy-key"},
            json={
                "model": "anthropic:claude-3-haiku-20240229",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["content"][0]["text"] == "Test reply"
        mock_chat.assert_awaited_once()


# ------------------------------------------------------------
# Streaming
# ------------------------------------------------------------


def _build_streaming_response() -> AsyncGenerator[bytes, None]:
    async def generator():
        yield b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        yield b'data: {"choices":[{"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"

    return generator()


def test_anthropic_messages_streaming_frontend(anthropic_client):
    from starlette.responses import StreamingResponse

    async_gen = _build_streaming_response()
    stream_response = StreamingResponse(async_gen, media_type="text/event-stream")

    with patch(
        "src.connectors.anthropic.AnthropicBackend.chat_completions",
        new_callable=AsyncMock,
    ) as mock_chat:
        mock_chat.return_value = stream_response

        res = anthropic_client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer test-proxy-key"},
            json={
                "model": "anthropic:claude-3-haiku-20240229",
                "stream": True,
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )
        collected = b"".join(list(res.iter_bytes()))
        text = collected.decode()
        assert "event: content_block_delta" in text
        assert "Hel" in text and "lo" in text
        mock_chat.assert_awaited_once()


# ------------------------------------------------------------
# Auth error
# ------------------------------------------------------------


def test_anthropic_messages_auth_failure(anthropic_client):
    res = anthropic_client.post(
        "/v1/messages",
        json={
            "model": "anthropic:claude-3-haiku-20240229",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert res.status_code == 401


# ------------------------------------------------------------
# Model listing
# ------------------------------------------------------------


def test_models_endpoint_includes_anthropic(anthropic_client):
    res = anthropic_client.get(
        "/models", headers={"Authorization": "Bearer test-proxy-key"}
    )
    assert res.status_code == 200
    models = {m["id"] for m in res.json()["data"]}
    assert "anthropic:claude-3-haiku-20240229" in models
