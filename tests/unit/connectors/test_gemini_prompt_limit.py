"""Tests for prompt size guard in Gemini OAuth connectors."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService
from src.core.config.app_config import AppConfig
from src.core.common.exceptions import InvalidRequestError


@pytest.fixture()
def oauth_plan_connector(monkeypatch):
    """Minimal Gemini OAuth plan connector with mocked OAuth credentials."""
    connector = GeminiOAuthPlanConnector(
        client=AsyncMock(),
        config=AppConfig(),
        translation_service=TranslationService(),
    )

    connector._oauth_credentials = {
        "access_token": "test-token",
        "expiry_date": 9999999999999,
    }
    connector._project_id = "test-project"
    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"

    # Avoid touching the filesystem or background watchers in tests
    monkeypatch.setattr(connector, "_start_file_watching", lambda: None)

    return connector


def _make_request() -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model="models/gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="hello")],
        stream=False,
    )


@pytest.mark.asyncio
async def test_non_streaming_prompt_overflow_is_blocked(oauth_plan_connector):
    connector = oauth_plan_connector

    connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    connector._discover_project_id = AsyncMock(return_value="test-project")  # type: ignore[attr-defined]

    request = _make_request()
    processed_messages = [{"role": "user", "content": "hello"}]

    with patch.object(
        connector,
        "_estimate_prompt_tokens",
        return_value=70_000,
    ), patch("asyncio.to_thread", side_effect=AssertionError("backend call should be skipped")):
        with pytest.raises(InvalidRequestError) as exc_info:
            await connector._chat_completions_code_assist(  # type: ignore[attr-defined]
                request_data=request,
                processed_messages=processed_messages,
                effective_model="models/gemini-2.5-pro",
            )

    err = exc_info.value
    assert err.status_code == 400
    assert err.code == "context_window_will_overflow"
    assert err.details["limit"] == 65_536
    assert err.details["estimated_tokens"] == 70_000


@pytest.mark.asyncio
async def test_streaming_prompt_overflow_is_blocked(oauth_plan_connector):
    connector = oauth_plan_connector

    connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    connector._discover_project_id = AsyncMock(return_value="test-project")  # type: ignore[attr-defined]

    request = _make_request().model_copy(update={"stream": True})
    processed_messages = [{"role": "user", "content": "hello"}]

    with patch.object(
        connector,
        "_estimate_prompt_tokens",
        return_value=80_000,
    ), patch("asyncio.to_thread", side_effect=AssertionError("backend call should be skipped")):
        with pytest.raises(InvalidRequestError) as exc_info:
            await connector._chat_completions_code_assist_streaming(  # type: ignore[attr-defined]
                request_data=request,
                processed_messages=processed_messages,
                effective_model="models/gemini-2.5-pro",
            )

    err = exc_info.value
    assert err.status_code == 400
    assert err.code == "context_window_will_overflow"
    assert err.details["limit"] == 65_536
    assert err.details["estimated_tokens"] == 80_000
