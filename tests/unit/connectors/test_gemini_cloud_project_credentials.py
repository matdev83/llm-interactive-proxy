"""
Tests for Gemini Cloud Project credential handling.
"""

import asyncio
import threading
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from src.connectors.gemini_cloud_project import GeminiCloudProjectConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService


def _make_connector() -> GeminiCloudProjectConnector:
    client = AsyncMock(spec=httpx.AsyncClient)
    config = AppConfig()
    return GeminiCloudProjectConnector(
        client,
        config,
        translation_service=TranslationService(),
        gcp_project_id="test-project",
    )


@pytest.mark.asyncio
async def test_schedule_credentials_reload_uses_main_loop(monkeypatch):
    """Credential reload scheduling should execute on the connector's main loop."""
    connector = _make_connector()
    connector._main_loop = asyncio.get_running_loop()

    reload_executed = asyncio.Event()

    async def fake_reload() -> None:
        reload_executed.set()

    connector._handle_credentials_file_change = AsyncMock(side_effect=fake_reload)

    def trigger_reload() -> None:
        connector._schedule_credentials_reload()

    thread = threading.Thread(target=trigger_reload)
    thread.start()
    thread.join()

    await asyncio.wait_for(reload_executed.wait(), timeout=0.2)
    await asyncio.sleep(0)
    assert connector._pending_reload_task is None


@pytest.mark.asyncio
async def test_chat_completions_refreshes_before_validation(monkeypatch):
    """Refresh must be attempted before runtime validation to avoid spurious 502s."""
    from tests.utils.fake_clock import FakeClock, FakeClockContext

    connector = _make_connector()
    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"
    connector.is_functional = True

    async with FakeClockContext(FakeClock(initial_time=1704067200.0)) as clock:
        connector._oauth_credentials = {
            "access_token": "initial-token",
            "expiry_date": int((clock.now() + 3600) * 1000),
        }

        call_order: list[str] = []

        async def fake_refresh() -> bool:
            call_order.append("refresh")
            return True

        async def fake_validate() -> bool:
            call_order.append("validate")
            return True

        connector._refresh_token_if_needed = AsyncMock(side_effect=fake_refresh)
        connector._validate_runtime_credentials = AsyncMock(side_effect=fake_validate)
        connector._ensure_healthy = AsyncMock()
        connector._chat_completions_standard = AsyncMock(return_value="ok-response")

        request = ChatRequest(
            model="gemini-cli-cloud-project:gemini-pro",
            messages=[ChatMessage(role="user", content="hi")],
            stream=False,
        )

        result = await connector.chat_completions(
            request_data=request,
            processed_messages=request.messages,
            effective_model="gemini-pro",
        )

        assert result == "ok-response"
        assert call_order == ["refresh", "validate"]


@pytest.mark.asyncio
async def test_chat_completions_raises_when_refresh_fails(monkeypatch):
    """If refresh fails, the request should be rejected with HTTP 502 without validation."""
    connector = _make_connector()
    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"
    connector.is_functional = True

    connector._refresh_token_if_needed = AsyncMock(return_value=False)
    connector._validate_runtime_credentials = AsyncMock(return_value=True)

    request = ChatRequest(
        model="gemini-cli-cloud-project:gemini-pro",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )

    with pytest.raises(HTTPException) as exc:
        await connector.chat_completions(
            request_data=request,
            processed_messages=request.messages,
            effective_model="gemini-pro",
        )

    assert exc.value.status_code == 502
    connector._validate_runtime_credentials.assert_not_called()
