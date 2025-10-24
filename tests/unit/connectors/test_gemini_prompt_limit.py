"""Tests for prompt size guard in Gemini OAuth connectors."""

from unittest.mock import AsyncMock, patch

import pytest
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
from src.core.common.exceptions import InvalidRequestError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


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


def _make_request(
    model: str = "models/gemini-2.5-pro", stream: bool = False
) -> CanonicalChatRequest:
    """Build a canonical chat request for the given model."""
    return CanonicalChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
        stream=stream,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("effective_model", "token_estimate", "expected_limit"),
    [
        ("models/gemini-2.5-pro", 1_100_000, 1_000_000),
        ("codechat-bison", 70_000, 65_536),
    ],
)
async def test_non_streaming_prompt_overflow_is_blocked(
    oauth_plan_connector,
    effective_model: str,
    token_estimate: int,
    expected_limit: int,
) -> None:
    connector = oauth_plan_connector

    connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    connector._discover_project_id = AsyncMock(return_value="test-project")  # type: ignore[attr-defined]

    request = _make_request(model=effective_model, stream=False)
    processed_messages = [{"role": "user", "content": "hello"}]

    with (
        patch.object(connector, "_estimate_prompt_tokens", return_value=token_estimate),
        patch(
            "asyncio.to_thread",
            side_effect=AssertionError("backend call should be skipped"),
        ),
        pytest.raises(InvalidRequestError) as exc_info,
    ):
        await connector._chat_completions_code_assist(  # type: ignore[attr-defined]
            request_data=request,
            processed_messages=processed_messages,
            effective_model=effective_model,
        )

    err = exc_info.value
    assert err.status_code == 400
    assert err.code == "context_window_will_overflow"
    assert err.details["limit"] == expected_limit
    assert err.details["estimated_tokens"] == token_estimate


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("effective_model", "token_estimate", "expected_limit"),
    [
        ("models/gemini-2.5-pro", 1_050_000, 1_000_000),
        ("codechat-bison", 80_000, 65_536),
    ],
)
async def test_streaming_prompt_overflow_is_blocked(
    oauth_plan_connector,
    effective_model: str,
    token_estimate: int,
    expected_limit: int,
) -> None:
    connector = oauth_plan_connector

    connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    connector._discover_project_id = AsyncMock(return_value="test-project")  # type: ignore[attr-defined]

    request = _make_request(model=effective_model, stream=True)
    processed_messages = [{"role": "user", "content": "hello"}]

    with (
        patch.object(connector, "_estimate_prompt_tokens", return_value=token_estimate),
        patch(
            "asyncio.to_thread",
            side_effect=AssertionError("backend call should be skipped"),
        ),
        pytest.raises(InvalidRequestError) as exc_info,
    ):
        await connector._chat_completions_code_assist_streaming(  # type: ignore[attr-defined]
            request_data=request,
            processed_messages=processed_messages,
            effective_model=effective_model,
        )

    err = exc_info.value
    assert err.status_code == 400
    assert err.code == "context_window_will_overflow"
    assert err.details["limit"] == expected_limit
    assert err.details["estimated_tokens"] == token_estimate
