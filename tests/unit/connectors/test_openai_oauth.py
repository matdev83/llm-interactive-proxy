import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
async def openai_oauth_backend_fixture(auth_dir: Path):
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

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
            await backend.initialize(openai_oauth_path=str(auth_dir))
            # Set the credentials for the test
            backend._auth_credentials = {"tokens": {"access_token": "chatgpt_token"}}
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

    # Mock runtime validation for the test
    with patch.object(
        openai_oauth_backend, "_validate_runtime_credentials", return_value=(True, [])
    ):
        await openai_oauth_backend.chat_completions(
            request_data=req,
            processed_messages=[ChatMessage(role="user", content="hi")],
            effective_model="gpt-4o-mini",
        )

    sent = httpx_mock.get_request()
    assert sent is not None
    # Ensure Authorization header uses access token
    assert sent.headers.get("Authorization") == "Bearer chatgpt_token"


@pytest.mark.asyncio
async def test_openai_oauth_reload_scheduled_from_thread(
    openai_oauth_backend: OpenAIOAuthConnector,
):
    backend = openai_oauth_backend

    reload_event = asyncio.Event()

    async def fake_load() -> bool:
        reload_event.set()
        return True

    with (
        patch.object(
            backend, "_load_auth", AsyncMock(side_effect=fake_load)
        ) as load_mock,
        patch.object(
            backend, "_validate_credentials_structure", return_value=(True, [])
        ),
    ):

        def trigger() -> None:
            backend._schedule_credentials_reload()

        thread = threading.Thread(target=trigger)
        thread.start()
        thread.join()

        await asyncio.wait_for(reload_event.wait(), timeout=1.0)
        load_mock.assert_awaited()

        # Allow callbacks to run so the pending task/future clears
        await asyncio.sleep(0)
        pending = backend._pending_reload_task
        assert pending is None or pending.done()
