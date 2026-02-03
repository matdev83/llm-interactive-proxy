from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector
from src.core.common.exceptions import BackendError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.mark.asyncio
async def test_chat_completions_rotates_on_project_not_found_backend_error() -> None:
    mock_client = MagicMock()
    mock_config = MagicMock()
    mock_config.get.return_value = False
    mock_config.backends = MagicMock()
    mock_translation_service = MagicMock()

    with (
        patch("src.connectors.gemini_oauth_auto.connector.TokenStorageService"),
        patch("src.connectors.gemini_oauth_auto.connector.TokenRefreshService"),
        patch("src.connectors.gemini_oauth_auto.connector.AccountSelectorService"),
    ):
        connector = GeminiOAuthAutoConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

    connector._enable_gemini_oauth_auto_backend_debugging_override = True
    connector.is_functional = True

    account1 = MagicMock()
    account1.account_id = "acct-1"
    account1.email = "a@example.com"
    account1.project_id = "bad-project"
    account1.to_credentials_dict.return_value = {}

    account2 = MagicMock()
    account2.account_id = "acct-2"
    account2.email = "b@example.com"
    account2.project_id = "good-project"
    account2.to_credentials_dict.return_value = {}

    current: dict[str, object] = {"account": account1}

    def _get_current_account() -> object | None:
        return current.get("account")

    async def _mark_account_uninitialized(account_id: str) -> None:
        acc = current.get("account")
        if getattr(acc, "account_id", None) == account_id:
            current["account"] = None

    async def _get_next_account(*, session_id: str | None = None) -> object:
        current["account"] = account2
        return account2

    selector = MagicMock()
    selector.get_current_account = MagicMock(side_effect=_get_current_account)
    selector.mark_account_uninitialized = AsyncMock(
        side_effect=_mark_account_uninitialized
    )
    selector.get_next_account = AsyncMock(side_effect=_get_next_account)
    selector.get_available_count = MagicMock(return_value=1)
    selector.mark_current_account_used = AsyncMock()
    selector.notification_service = None

    connector._account_selector = selector

    inner_request = CanonicalChatRequest(
        model="google/gemini-3-flash-preview",
        messages=[ChatMessage(role="user", content="hello")],
        stream=False,
    )
    request = ConnectorChatCompletionsRequest(
        request=inner_request,
        processed_messages=[ChatMessage(role="user", content="hello")],
        effective_model="gemini-oauth-auto:google/gemini-3-flash-preview",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )

    error = BackendError(
        message="Requested entity was not found.",
        code="api_error",
        status_code=404,
        details={"error": {"status": "NOT_FOUND"}},
        backend_name="gemini-oauth-auto",
    )

    response = ResponseEnvelope(content={"ok": True})

    chat_mock = AsyncMock(side_effect=[error, response])
    with patch(
        "src.connectors.gemini_oauth_base.GeminiOAuthBaseConnector.chat_completions",
        new=chat_mock,
    ):
        result = await connector.chat_completions(request)

    assert chat_mock.await_count == 2
    selector.mark_account_uninitialized.assert_awaited_once_with("acct-1")
    selector.get_next_account.assert_awaited_once()
    assert isinstance(result, ResponseEnvelope)
    assert result.metadata is not None
    assert result.metadata["account_id"] == "acct-2"


@pytest.mark.asyncio
async def test_chat_completions_rotates_on_project_not_found_streaming_error() -> None:
    mock_client = MagicMock()
    mock_config = MagicMock()
    mock_config.get.return_value = False
    mock_config.backends = MagicMock()
    mock_translation_service = MagicMock()

    with (
        patch("src.connectors.gemini_oauth_auto.connector.TokenStorageService"),
        patch("src.connectors.gemini_oauth_auto.connector.TokenRefreshService"),
        patch("src.connectors.gemini_oauth_auto.connector.AccountSelectorService"),
    ):
        connector = GeminiOAuthAutoConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

    connector._enable_gemini_oauth_auto_backend_debugging_override = True
    connector.is_functional = True
    connector._STREAM_PRIME_TIMEOUT_SECONDS = 0.01

    account1 = MagicMock()
    account1.account_id = "acct-1"
    account1.email = "a@example.com"
    account1.project_id = "bad-project"
    account1.to_credentials_dict.return_value = {}

    account2 = MagicMock()
    account2.account_id = "acct-2"
    account2.email = "b@example.com"
    account2.project_id = "good-project"
    account2.to_credentials_dict.return_value = {}

    current: dict[str, object] = {"account": account1}

    def _get_current_account() -> object | None:
        return current.get("account")

    async def _mark_account_uninitialized(account_id: str) -> None:
        acc = current.get("account")
        if getattr(acc, "account_id", None) == account_id:
            current["account"] = None

    async def _get_next_account(*, session_id: str | None = None) -> object:
        current["account"] = account2
        return account2

    selector = MagicMock()
    selector.get_current_account = MagicMock(side_effect=_get_current_account)
    selector.mark_account_uninitialized = AsyncMock(
        side_effect=_mark_account_uninitialized
    )
    selector.get_next_account = AsyncMock(side_effect=_get_next_account)
    selector.get_available_count = MagicMock(return_value=1)
    selector.mark_current_account_used = AsyncMock()
    selector.notification_service = None

    connector._account_selector = selector

    inner_request = CanonicalChatRequest(
        model="google/gemini-3-flash-preview",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
    )
    request = ConnectorChatCompletionsRequest(
        request=inner_request,
        processed_messages=[ChatMessage(role="user", content="hello")],
        effective_model="gemini-oauth-auto:google/gemini-3-flash-preview",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )

    error = BackendError(
        message="Requested entity was not found.",
        code="api_error",
        status_code=404,
        details={"error": {"status": "NOT_FOUND"}},
        backend_name="gemini-oauth-auto",
    )

    async def _bad_stream() -> AsyncIterator[ProcessedResponse]:
        raise error
        if False:  # pragma: no cover
            yield ProcessedResponse(content={})

    response = ResponseEnvelope(content={"ok": True})

    chat_mock = AsyncMock(
        side_effect=[
            StreamingResponseEnvelope(content=_bad_stream()),
            response,
        ]
    )
    with patch(
        "src.connectors.gemini_oauth_base.GeminiOAuthBaseConnector.chat_completions",
        new=chat_mock,
    ):
        result = await connector.chat_completions(request)

    assert chat_mock.await_count == 2
    selector.mark_account_uninitialized.assert_awaited_once_with("acct-1")
    selector.get_next_account.assert_awaited_once()
    assert isinstance(result, ResponseEnvelope)
    assert result.metadata is not None
    assert result.metadata["account_id"] == "acct-2"
