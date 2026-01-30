from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


@pytest.mark.asyncio
async def test_chat_completions_unpacks_canonical_request(mocker):
    """
    Regression test ensuring GeminiOAuthPlanConnector.chat_completions correctly unpacks
    the canonical ConnectorChatCompletionsRequest into legacy arguments expected by the parent class.

    This prevents the TypeError: "chat_completions() missing required positional arguments"
    or passing the wrong first argument type to the parent.
    """
    # Arrange
    mock_client = AsyncMock()
    mock_config = MagicMock(spec=AppConfig)
    # Enable the debug override so the connector doesn't raise 403
    mock_config.backends = MagicMock()
    mock_config.backends.gemini_oauth_plan = MagicMock()
    mock_config.backends.gemini_oauth_plan.extra = {
        "enable_gemini_oauth_plan_backend_debugging_override": True
    }

    mock_translation_service = MagicMock()

    connector = GeminiOAuthPlanConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
    )
    # Set required base URL that normally comes from initialize()
    connector.gemini_api_base_url = "https://cloudaicompanion-pa.googleapis.com"

    # Prepare input data
    chat_req = CanonicalChatRequest(
        model="gemini-pro", messages=[ChatMessage(role="user", content="hello")]
    )
    processed_msgs = [ChatMessage(role="user", content="hello")]
    identity_mock = MagicMock()
    cancel_token_mock = MagicMock()
    cancel_coord_mock = MagicMock()

    request = ConnectorChatCompletionsRequest(
        request=chat_req,
        processed_messages=processed_msgs,
        effective_model="gemini-pro",
        identity=identity_mock,
        cancellation_token=cancel_token_mock,
        cancellation_coordinator=cancel_coord_mock,
        context=ConnectorRequestContext(
            request_id="req-1", session_id="sess-1", client_host="1.2.3.4"
        ),
        options={"some_option": "some_value"},
    )

    # Act & Assert
    # Mock runtime credential validation to skip token refresh logic
    mocker.patch.object(connector, "_validate_runtime_credentials", new_callable=AsyncMock, return_value=True)

    # We patch the facade class's chat_completions method which GeminiOAuthPlanConnector calls via super().
    mock_super_chat = mocker.patch(
        "src.connectors.gemini_oauth_base.GeminiOAuthBaseConnector.chat_completions",
        new_callable=AsyncMock,
    )

    await connector.chat_completions(request)

    # Verify call arguments
    mock_super_chat.assert_called_once()

    call_kwargs = mock_super_chat.call_args.kwargs

    # Verify arguments are unpacked correctly
    assert call_kwargs["request_data"] == chat_req
    assert call_kwargs["processed_messages"] == processed_msgs
    assert call_kwargs["effective_model"] == "gemini-pro"
    assert call_kwargs["identity"] == identity_mock
    assert call_kwargs["cancellation_token"] == cancel_token_mock
    assert call_kwargs["cancellation_coordinator"] == cancel_coord_mock

    # Verify kwargs unpacking (options)
    assert call_kwargs["some_option"] == "some_value"
