from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig


@pytest.mark.asyncio
async def test_openai_connector_identity_headers_isolated_per_request() -> None:
    client = httpx.AsyncClient()
    connector = OpenAIConnector(
        client=client,
        config=AppConfig(),
        translation_service=Mock(),
    )
    connector.api_key = "test-key"

    connector._ensure_healthy = AsyncMock()  # type: ignore[attr-defined]
    connector._prepare_payload = AsyncMock(return_value={})  # type: ignore[attr-defined]

    captured_headers: dict[str, dict[str, str]] = {}

    async def fake_handle(
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
        context: Any | None = None,
    ) -> ResponseEnvelope:
        captured_headers[session_id] = dict(headers or {})
        return ResponseEnvelope(content={}, status_code=200, headers={})

    connector._handle_non_streaming_response = AsyncMock(  # type: ignore[attr-defined]
        side_effect=fake_handle
    )

    request_a = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hello")],
        stream=False,
        session_id="session-alpha",
    )
    request_b = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi again")],
        stream=False,
        session_id="session-beta",
    )
    request_c = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="final call")],
        stream=False,
        session_id="session-gamma",
    )

    identity_a = Mock(spec=IAppIdentityConfig)
    identity_a.get_resolved_headers.return_value = {"X-Test": "alpha"}

    identity_b = Mock(spec=IAppIdentityConfig)
    identity_b.get_resolved_headers.return_value = {"X-Test": "beta"}

    await asyncio.gather(
        connector.chat_completions(
            request_data=request_a,
            processed_messages=[],
            effective_model="gpt-4",
            identity=identity_a,
        ),
        connector.chat_completions(
            request_data=request_b,
            processed_messages=[],
            effective_model="gpt-4",
            identity=identity_b,
        ),
    )

    await connector.chat_completions(
        request_data=request_c,
        processed_messages=[],
        effective_model="gpt-4",
        identity=None,
    )

    try:
        alpha_headers = captured_headers["session-alpha"]
        beta_headers = captured_headers["session-beta"]
        gamma_headers = captured_headers["session-gamma"]
    finally:
        await client.aclose()

    assert alpha_headers["X-Test"] == "alpha"
    assert beta_headers["X-Test"] == "beta"
    # Authorization header should be present on every request
    assert alpha_headers["Authorization"] == "Bearer test-key"
    assert beta_headers["Authorization"] == "Bearer test-key"
    assert gamma_headers["Authorization"] == "Bearer test-key"
    # Identity headers should not leak into requests that omit identity
    assert "X-Test" not in gamma_headers
