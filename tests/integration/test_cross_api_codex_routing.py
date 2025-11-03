from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendSettings,
    LoggingConfig,
    SessionConfig,
)
from src.core.domain.responses import ResponseEnvelope


@pytest.fixture()
def mocked_codex_test_client() -> (
    Iterator[tuple[TestClient, AuthConfig, AsyncMock, AsyncMock, AsyncMock]]
):
    """Build a test client with a fully mocked OpenAI Codex connector."""
    with (
        patch("src.core.config.app_config.load_config") as mock_load_config,
        patch(
            "src.connectors.openai_codex.OpenAICodexConnector.initialize",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "src.connectors.openai_codex.OpenAICodexConnector.chat_completions",
            new_callable=AsyncMock,
        ) as mock_chat,
        patch(
            "src.connectors.openai_codex.OpenAICodexConnector.is_backend_functional",
            return_value=True,
        ),
        patch(
            "src.core.services.backend_service.BackendService.call_completion",
            new_callable=AsyncMock,
        ) as mock_call_completion,
    ):
        auth = AuthConfig(disable_auth=False, api_keys=["test-proxy-key"])
        config = AppConfig(
            auth=auth,
            proxy_timeout=10,
            session=SessionConfig(default_interactive_mode=False),
            command_prefix="!/",
            backends=BackendSettings(default_backend="openai-codex"),
            logging=LoggingConfig(),
        )
        mock_load_config.return_value = config
        app = build_test_app(config)
        with TestClient(app) as client:
            yield client, auth, mock_init, mock_chat, mock_call_completion


def _build_codex_response(content_text: str) -> ResponseEnvelope:
    """Return a simple Codex ChatResponse wrapped in a ResponseEnvelope."""
    response = {
        "id": "codex-response-1",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-5-codex",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
    }
    return ResponseEnvelope(
        content=response,
        status_code=200,
        headers={"content-type": "application/json"},
    )


def test_anthropic_frontend_routes_to_openai_codex(
    mocked_codex_test_client: tuple[
        TestClient, AuthConfig, AsyncMock, AsyncMock, AsyncMock
    ],
) -> None:
    client, auth, mock_init, mock_chat, mock_call_completion = mocked_codex_test_client

    mock_init.return_value = None
    mock_call_completion.return_value = _build_codex_response("Hello from Codex")

    response = client.post(
        "/anthropic/v1/messages",
        headers={"Authorization": f"Bearer {auth.api_keys[0]}"},
        json={
            "model": "openai-codex:gpt-5-codex",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "message"
    assert payload["content"][0]["text"] == "Hello from Codex"

    mock_call_completion.assert_awaited_once()


def test_gemini_frontend_routes_to_openai_codex(
    mocked_codex_test_client: tuple[
        TestClient, AuthConfig, AsyncMock, AsyncMock, AsyncMock
    ],
) -> None:
    client, auth, mock_init, mock_chat, mock_call_completion = mocked_codex_test_client

    mock_init.return_value = None
    mock_call_completion.return_value = _build_codex_response("Gemini via Codex")

    response = client.post(
        "/v1beta/models/openai-codex:gpt-5-codex:generateContent",
        headers={"Authorization": f"Bearer {auth.api_keys[0]}"},
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Hello Codex through Gemini"}],
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidates"][0]["content"]["parts"][0]["text"] == "Gemini via Codex"

    mock_call_completion.assert_awaited_once()
