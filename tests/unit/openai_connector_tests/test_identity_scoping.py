from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.openai import OpenAIConnector
from src.connectors.openai_responses import OpenAIResponsesConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig


class DummyIdentity(IAppIdentityConfig):
    """Simple identity implementation returning static headers."""

    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    def get_resolved_headers(
        self, incoming_headers: dict[str, Any] | None
    ) -> dict[str, str]:
        return dict(self._headers)


def _build_request(stream: bool = False) -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hello")],
        stream=stream,
    )


@pytest.mark.asyncio
async def test_chat_completions_clears_identity_between_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    connector = OpenAIConnector(client=client, config=AppConfig())
    connector.api_key = "token"

    observed_headers: list[dict[str, str] | None] = []

    async def fake_handle(
        self: OpenAIConnector,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> ResponseEnvelope:
        observed_headers.append(headers)
        return ResponseEnvelope(content={}, headers={}, status_code=200)

    monkeypatch.setattr(
        OpenAIConnector,
        "_handle_non_streaming_response",
        fake_handle,
    )

    request = _build_request()
    identity = DummyIdentity({"X-Test": "one"})

    await connector.chat_completions(request, [], "gpt-4", identity=identity)
    await connector.chat_completions(request, [], "gpt-4", identity=None)

    assert observed_headers[0] is not None
    assert observed_headers[1] is not None
    assert observed_headers[0].get("X-Test") == "one"
    assert "X-Test" not in observed_headers[1]


@pytest.mark.asyncio
async def test_chat_completions_uses_identity_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    connector = OpenAIConnector(client=client, config=AppConfig())
    connector.disable_health_check()

    observed_headers: list[dict[str, str] | None] = []

    async def fake_handle(
        self: OpenAIConnector,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> ResponseEnvelope:
        observed_headers.append(headers)
        return ResponseEnvelope(content={}, headers={}, status_code=200)

    monkeypatch.setattr(
        OpenAIConnector,
        "_handle_non_streaming_response",
        fake_handle,
    )

    request = _build_request()
    identity = DummyIdentity({"Authorization": "Bearer identity-token"})

    await connector.chat_completions(request, [], "gpt-4", identity=identity)

    assert observed_headers
    assert observed_headers[0] is not None
    assert observed_headers[0].get("Authorization") == "Bearer identity-token"


@pytest.mark.asyncio
async def test_responses_clears_identity_between_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    translation_service = MagicMock()

    domain_request = _build_request()
    translation_service.to_domain_request.return_value = domain_request
    translation_service.from_domain_to_responses_request.return_value = {
        "model": domain_request.model,
        "messages": [],
    }

    connector = OpenAIResponsesConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )
    connector.api_key = "token"

    observed_headers: list[dict[str, str] | None] = []

    async def fake_responses_handle(
        self: OpenAIConnector,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> ResponseEnvelope:
        observed_headers.append(headers)
        return ResponseEnvelope(content={}, headers={}, status_code=200)

    monkeypatch.setattr(
        OpenAIConnector,
        "_handle_responses_non_streaming_response",
        fake_responses_handle,
    )

    identity = DummyIdentity({"X-Test": "one"})
    request_payload: dict[str, Any] = {
        "model": "gpt-4",
        "messages": [
            {"role": "user", "content": "hello"},
        ],
        "stream": False,
    }

    await connector.responses(request_payload, [], "gpt-4", identity=identity)
    await connector.responses(request_payload, [], "gpt-4", identity=None)

    assert observed_headers[0] is not None
    assert observed_headers[1] is not None
    assert observed_headers[0].get("X-Test") == "one"
    assert "X-Test" not in observed_headers[1]
