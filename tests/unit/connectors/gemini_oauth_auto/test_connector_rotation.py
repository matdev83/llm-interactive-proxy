"""
Unit tests for GeminiOAuthAutoConnector rotation logic.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector
from src.core.common.exceptions import BackendError


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.get.return_value = False
    config.backends = MagicMock()
    return config


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def mock_translation_service():
    return MagicMock()


@pytest.fixture
def connector(mock_client, mock_config, mock_translation_service):
    with (
        patch("src.connectors.gemini_oauth_auto.connector.TokenStorageService"),
        patch("src.connectors.gemini_oauth_auto.connector.TokenRefreshService"),
        patch(
            "src.connectors.gemini_oauth_auto.connector.AccountSelectorService"
        ) as mock_selector_cls,
    ):

        mock_selector = mock_selector_cls.return_value
        mock_selector.rotate_on_quota = AsyncMock()
        mock_selector.mark_current_account_used = AsyncMock()
        mock_selector.get_next_account = AsyncMock()
        mock_selector.reload_accounts = AsyncMock()
        mock_selector.get_current_account = MagicMock()
        mock_selector.get_available_count = MagicMock(return_value=1)

        conn = GeminiOAuthAutoConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )
        conn._account_selector = mock_selector
        conn._enable_gemini_oauth_auto_backend_debugging_override = True
        conn.is_functional = True

        # Mock coordinator to avoid real execution and control results
        mock_coordinator = AsyncMock()
        conn._chat_completion_coordinator = mock_coordinator

        conn._mark_backend_unusable = MagicMock(wraps=conn._mark_backend_unusable)

        yield conn


@pytest.mark.asyncio
async def test_chat_completions_triggers_rotation_on_backend_error(connector):
    """Test that chat_completions triggers rotation when BackendError(quota_exceeded) is raised."""
    # Setup
    error = BackendError(message="Quota exceeded", code="quota_exceeded")
    connector._chat_completion_coordinator.execute.side_effect = error

    # Create a real request object instead of MagicMock to avoid attribute errors in base class
    from src.connectors.contracts import ConnectorChatCompletionsRequest
    from src.core.domain.chat import CanonicalChatRequest, ChatMessage

    inner_request = CanonicalChatRequest(
        model="gemini-pro", messages=[ChatMessage(role="user", content="hello")]
    )
    request = ConnectorChatCompletionsRequest(
        request=inner_request,
        processed_messages=[],
        effective_model="gemini-oauth-auto:gemini-pro",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )

    # Execute
    with pytest.raises(BackendError):
        await connector.chat_completions(request)

    # Verify
    connector._mark_backend_unusable.assert_called_with(
        reason="quota_exceeded", retry_after_seconds=None
    )

    await asyncio.sleep(0.01)
    connector._account_selector.rotate_on_quota.assert_called_once()
