from unittest.mock import AsyncMock

import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.common.exceptions import InvalidRequestError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


@pytest.mark.asyncio
async def test_openai_codex_degrades_on_http_auth_error(monkeypatch):
    client = AsyncMock()
    config = AppConfig()
    mock_translation_service = AsyncMock(spec=TranslationService)
    connector = OpenAICodexConnector(
        client=client, config=config, translation_service=mock_translation_service
    )
    connector.is_functional = True
    connector.api_key = "token"
    connector._auth_credentials = {"tokens": {"access_token": "token"}}

    async def fake_validate_runtime_credentials(self: OpenAICodexConnector):
        return True

    async def fake_load_auth(self: OpenAICodexConnector) -> bool:
        return True

    mock_codex_call = AsyncMock(
        side_effect=InvalidRequestError(
            message="invalid token", status_code=401, details={}
        )
    )

    monkeypatch.setattr(
        OpenAICodexConnector,
        "_validate_runtime_credentials",
        fake_validate_runtime_credentials,
    )
    monkeypatch.setattr(OpenAICodexConnector, "_load_auth", fake_load_auth)
    monkeypatch.setattr(
        OpenAICodexConnector, "_call_codex_responses_api", mock_codex_call
    )

    with pytest.raises(InvalidRequestError):
        request = CanonicalChatRequest(
            model="gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="test")],
        )
        connector_req = ConnectorChatCompletionsRequest(
            request=request,
            processed_messages=list(request.messages),
            effective_model="gpt-5.4-mini",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )
        await connector.chat_completions(connector_req)

    assert connector.is_functional is False
