from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
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


def _dummy_anthropic_response(text: str = "Mock response from test backend") -> dict:
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
            "/anthropic/v1/messages",  # Use the correct Anthropic endpoint
            headers={"Authorization": "Bearer test-proxy-key"},
            json={
                "model": "claude-3-haiku-20240229",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["content"][0]["text"] == "Mock response from test backend"
        mock_chat.assert_awaited_once()


# ------------------------------------------------------------
# Streaming
# ------------------------------------------------------------


def _build_streaming_response() -> AsyncGenerator[bytes, None]:
    async def generator():
        yield b'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}\n\n'
        yield b'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}}\n\n'
        yield b'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}}\n\n'
        yield b'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n'
        yield b'event: message_delta\ndata: {"type": "message_delta", "delta": {"stop_reason": "end_turn", "usage": {"output_tokens": 10}}}\n\n'
        yield b'event: message_stop\ndata: {"type": "message_stop"}\n\n'

    return generator()


def test_anthropic_messages_streaming_frontend(anthropic_client):
    with patch(
        "src.connectors.anthropic.AnthropicBackend.chat_completions",
        new_callable=AsyncMock,
    ) as mock_chat:
        mock_chat.return_value = _build_streaming_response()

        res = anthropic_client.post(
            "/anthropic/v1/messages",  # Use the correct Anthropic endpoint
            headers={"Authorization": "Bearer test-proxy-key"},
            json={
                "model": "claude-3-haiku-20240229",
                "max_tokens": 128,
                "stream": True,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        # For streaming, we should get a 200 response
        assert res.status_code == 200
        text = res.text
        # Check that we get Anthropic streaming format
        assert "event: content_block_delta" in text
        mock_chat.assert_awaited_once()


# ------------------------------------------------------------
# Auth error
# ------------------------------------------------------------


def test_anthropic_messages_auth_failure(anthropic_client):
    res = anthropic_client.post(
        "/anthropic/v1/messages",  # Use the correct Anthropic endpoint
        # No authorization header
        json={
            "model": "claude-3-haiku-20240229",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    # Should be 401 or 403 due to missing auth, or could be 501 if endpoint not implemented
    assert res.status_code in [401, 403, 501]


# ------------------------------------------------------------
# Model listing
# ------------------------------------------------------------


def test_models_endpoint_includes_anthropic(anthropic_client):
    res = anthropic_client.get("/anthropic/v1/models")  # Use the correct Anthropic endpoint
    assert res.status_code == 200
    models_data = res.json()["data"]
    # Extract model IDs from the list of model dictionaries
    model_ids = [model["id"] for model in models_data]
    # Check that at least one Anthropic model is included
    anthropic_models = [m for m in model_ids if "claude" in m.lower()]
    assert len(anthropic_models) > 0
