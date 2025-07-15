from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from src.main import build_app
from src.models import ChatCompletionResponse, ChatCompletionChoice, ChatCompletionChoiceMessage, CompletionUsage


@pytest.fixture()
def test_app():
    """Create FastAPI test app with config patched for Anthropic."""
    with patch("src.main._load_config") as mock_cfg, \
         patch("src.connectors.anthropic.AnthropicBackend.get_available_models", return_value=["claude-3-haiku-20240229"]):
        mock_cfg.return_value = {
            "disable_auth": False,
            "disable_accounting": True,
            "proxy_timeout": 10,
            "interactive_mode": False,
            "command_prefix": "!/",
            "anthropic_api_keys": {"ANTHROPIC_API_KEY_1": "ant-key"},
            "anthropic_api_base_url": "https://api.anthropic.com/v1",
            # Keep other back-ends minimal but valid
            "openrouter_api_keys": {},
            "gemini_api_keys": {},
        }
        app = build_app()
        app.state.client_api_key = "client-key"
        with TestClient(app) as client:
            yield client


def _dummy_openai_response(text: str = "Test reply") -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-001",
        created=1234567890,
        model="anthropic/claude-3-haiku-20240229",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(role="assistant", content=text),
                finish_reason="stop",
            )
        ],
        usage=CompletionUsage(prompt_tokens=5, completion_tokens=7, total_tokens=12),
    )


# ------------------------------------------------------------
# Non-streaming
# ------------------------------------------------------------

def test_anthropic_messages_non_streaming_frontend(test_app):
    with patch("src.connectors.anthropic.AnthropicBackend.chat_completions", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = (_dummy_openai_response().model_dump(exclude_none=True), {})

        res = test_app.post(
            "/v1/messages",
            headers={"x-api-key": "client-key"},
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
        yield b"data: {\"choices\":[{\"delta\":{\"content\":\"Hel\"}}]}\n\n"
        yield b"data: {\"choices\":[{\"delta\":{\"content\":\"lo\"}}]}\n\n"
        yield b"data: {\"choices\":[{\"finish_reason\":\"stop\"}]}\n\n"
        yield b"data: [DONE]\n\n"
    return generator()


def test_anthropic_messages_streaming_frontend(test_app):
    from starlette.responses import StreamingResponse

    async_gen = _build_streaming_response()
    stream_response = StreamingResponse(async_gen, media_type="text/event-stream")

    with patch("src.connectors.anthropic.AnthropicBackend.chat_completions", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = stream_response

        res = test_app.post(
            "/v1/messages",
            headers={"x-api-key": "client-key"},
            json={
                "model": "anthropic:claude-3-haiku-20240229",
                "stream": True,
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Hi"}],
            },
            stream=True,
        )
        collected = b"".join(list(res.iter_bytes()))
        text = collected.decode()
        assert "event: content_block_delta" in text
        assert "Hel" in text and "lo" in text
        mock_chat.assert_awaited_once()


# ------------------------------------------------------------
# Auth error
# ------------------------------------------------------------

def test_anthropic_messages_auth_failure(test_app):
    res = test_app.post(
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

def test_models_endpoint_includes_anthropic(test_app):
    res = test_app.get(
        "/models",
        headers={"Authorization": "Bearer client-key"},
    )
    assert res.status_code == 200
    models = {m["id"] for m in res.json()["data"]}
    assert "anthropic:claude-3-haiku-20240229" in models 