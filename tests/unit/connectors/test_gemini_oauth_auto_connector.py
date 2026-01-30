from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.mark.asyncio
async def test_oauth_auto_skips_blocked_account_on_403() -> None:
    client = MagicMock()
    config = AppConfig({})
    translation_service = MagicMock()

    connector = GeminiOAuthAutoConnector(
        client=client,
        config=config,
        translation_service=translation_service,
    )
    connector._enable_gemini_oauth_auto_backend_debugging_override = True

    account_selector = MagicMock()
    account_selector.get_current_account.return_value = None
    account_selector.get_available_count.return_value = 1
    account_selector.mark_current_account_blocked = AsyncMock()
    account_selector.mark_current_account_used = AsyncMock()
    connector._account_selector = account_selector

    request = CanonicalChatRequest(
        model="gemini-3-pro",
        messages=[ChatMessage(role="user", content="hello")],
        stream=False,
    )
    connector_request = ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=[ChatMessage(role="user", content="hello")],
        effective_model="gemini-oauth-auto:gemini-3-pro",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
    )

    blocked_error = BackendError(
        message="To continue, verify your account at https://accounts.google.com/",
        status_code=403,
        backend_name="gemini-oauth-auto",
    )
    success_response = ResponseEnvelope(content={"ok": True})

    with patch(
        "src.connectors.gemini_oauth_base.GeminiOAuthBaseConnector.chat_completions",
        new=AsyncMock(side_effect=[blocked_error, success_response]),
    ) as base_call:
        result = await connector.chat_completions(connector_request)

    assert result == success_response
    assert base_call.await_count == 2
    account_selector.mark_current_account_blocked.assert_awaited_once()
    account_selector.mark_current_account_used.assert_awaited_once()


@pytest.mark.asyncio
async def test_oauth_auto_blocks_account_on_streaming_403_chunk() -> None:
    client = MagicMock()
    config = AppConfig({})
    translation_service = MagicMock()

    connector = GeminiOAuthAutoConnector(
        client=client,
        config=config,
        translation_service=translation_service,
    )

    account_selector = MagicMock()
    account_selector.mark_current_account_blocked = AsyncMock()
    connector._account_selector = account_selector

    async def _error_stream():
        yield ProcessedResponse(
            content={"id": "chunk-1"},
            metadata={
                "error": {
                    "type": "forbidden",
                    "code": 403,
                    "message": "To continue, verify your account at https://accounts.google.com/",
                }
            },
        )

    collected: list[ProcessedResponse] = []
    async for chunk in connector._wrap_stream_for_rotation(_error_stream()):
        collected.append(chunk)

    assert len(collected) == 1
    account_selector.mark_current_account_blocked.assert_awaited_once()


@pytest.mark.asyncio
async def test_oauth_auto_streaming_chat_completions_wraps_blocked_errors() -> None:
    client = MagicMock()
    config = AppConfig({})
    translation_service = MagicMock()

    connector = GeminiOAuthAutoConnector(
        client=client,
        config=config,
        translation_service=translation_service,
    )
    connector._enable_gemini_oauth_auto_backend_debugging_override = True

    account_selector = MagicMock()
    account_selector.mark_current_account_blocked = AsyncMock()
    account_selector.mark_current_account_used = AsyncMock()
    connector._account_selector = account_selector

    request = CanonicalChatRequest(
        model="gemini-3-pro",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
    )
    connector_request = ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=[ChatMessage(role="user", content="hello")],
        effective_model="gemini-oauth-auto:gemini-3-pro",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
    )

    async def _error_stream():
        yield ProcessedResponse(
            content={"id": "chunk-1"},
            metadata={
                "error": {
                    "type": "forbidden",
                    "code": 403,
                    "message": "To continue, verify your account at https://accounts.google.com/",
                }
            },
        )

    streaming_response = StreamingResponseEnvelope(content=_error_stream())

    with patch(
        "src.connectors.gemini_oauth_base.GeminiOAuthBaseConnector.chat_completions",
        new=AsyncMock(return_value=streaming_response),
    ):
        result = await connector.chat_completions(connector_request)

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None

    async for _ in result.content:
        pass

    account_selector.mark_current_account_blocked.assert_awaited_once()


@pytest.mark.parametrize(
    "message",
    [f"Error: {marker}" for marker in GeminiOAuthAutoConnector._ACCOUNT_BLOCK_MARKERS],
)
def test_oauth_auto_blocked_message_variants(message: str) -> None:
    assert GeminiOAuthAutoConnector._is_account_blocked_message(
        message,
        status_code=403,
        details=None,
    )


@pytest.mark.parametrize(
    "details",
    [
        {"message": "To continue, verify your account"},
        {"error": {"message": "Validate your account to proceed"}},
        {"error": "Account suspended"},
        {
            "error": {
                "message": "We detected suspicious activity. Confirm your identity"
            }
        },
    ],
)
def test_oauth_auto_blocked_message_from_details(details: dict[str, object]) -> None:
    assert GeminiOAuthAutoConnector._is_account_blocked_message(
        None,
        status_code=403,
        details=details,
    )
