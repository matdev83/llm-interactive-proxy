import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.openai_oauth import OpenAIOAuthConnector
from src.core.domain.chat import ChatMessage, ChatRequest


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    # Minimal auth.json with tokens.access_token
    data = {"tokens": {"access_token": "chatgpt_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="openai_oauth_backend")
async def openai_oauth_backend_fixture(auth_dir: Path) -> OpenAIOAuthConnector:
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)
        await backend.initialize(openai_oauth_path=str(auth_dir))
        yield backend


@pytest.mark.asyncio
async def test_openai_oauth_uses_bearer_from_auth_json(
    openai_oauth_backend: OpenAIOAuthConnector, httpx_mock: HTTPXMock
):
    # Mock chat completion
    httpx_mock.add_response(
        url=f"{openai_oauth_backend.api_base_url}/chat/completions",
        method="POST",
        json={
            "id": "cmpl_1",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    req = ChatRequest(
        model="openai-oauth:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=16,
        stream=False,
    )

    await openai_oauth_backend.chat_completions(
        request_data=req,
        processed_messages=[ChatMessage(role="user", content="hi")],
        effective_model="gpt-4o-mini",
    )

    sent = httpx_mock.get_request()
    assert sent is not None
    # Ensure Authorization header uses access token
    assert sent.headers.get("Authorization") == "Bearer chatgpt_token"
