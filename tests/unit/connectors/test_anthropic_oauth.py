import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.anthropic import (
    ANTHROPIC_DEFAULT_BASE_URL,
    ANTHROPIC_VERSION_HEADER,
)
from src.connectors.anthropic_oauth import AnthropicOAuthBackend
from src.core.domain.chat import ChatMessage, ChatRequest


@pytest_asyncio.fixture(name="oauth_creds_tmp")
async def oauth_creds_tmp_dir(tmp_path: Path):
    # Create a faux oauth_creds.json in a temp directory
    creds = {"access_token": "oauth_test_token"}
    (tmp_path / "oauth_creds.json").write_text(json.dumps(creds), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="anthropic_oauth_backend")
async def anthropic_oauth_backend_fixture(
    oauth_creds_tmp: Path,
):
    async with httpx.AsyncClient() as client:
        from unittest.mock import patch

        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = AnthropicOAuthBackend(client, cfg, ts)

        # Mock the validation and file watching methods for testing
        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            # Initialize with explicit oauth dir override
            await backend.initialize(
                anthropic_oauth_path=str(oauth_creds_tmp),
                anthropic_api_base_url=ANTHROPIC_DEFAULT_BASE_URL,
            )
            # Set the credentials for the test
            backend._oauth_credentials = {"access_token": "oauth_test_token"}
            yield backend


@pytest.mark.asyncio
async def test_anthropic_oauth_sends_x_api_key(
    anthropic_oauth_backend: AnthropicOAuthBackend, httpx_mock: HTTPXMock
) -> None:
    from unittest.mock import patch

    # Mock the POST /messages response
    httpx_mock.add_response(
        url=f"{ANTHROPIC_DEFAULT_BASE_URL}/messages",
        method="POST",
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "OK"}],
            "model": "claude-3-haiku-20240307",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    req = ChatRequest(
        model="anthropic-oauth:claude-3-haiku-20240307",
        messages=[ChatMessage(role="user", content="hello")],
        max_tokens=32,
        stream=False,
    )

    # Mock runtime validation for the test
    with patch.object(
        anthropic_oauth_backend,
        "_validate_runtime_credentials",
        return_value=(True, []),
    ):
        await anthropic_oauth_backend.chat_completions(
            request_data=req,
            processed_messages=[ChatMessage(role="user", content="hello")],
            effective_model="claude-3-haiku-20240307",
        )

    sent = httpx_mock.get_request()
    assert sent is not None
    assert sent.headers.get("anthropic-version") == ANTHROPIC_VERSION_HEADER
    # The oauth access_token must be used as x-api-key
    assert sent.headers.get("x-api-key") == "oauth_test_token"
