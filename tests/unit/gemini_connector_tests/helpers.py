"""Shared helpers for GeminiBackend unit tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock

from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest


def gemini_connector_request(
    request: ChatRequest | CanonicalChatRequest,
    *,
    processed_messages: list[ChatMessage],
    effective_model: str,
    options: dict[str, Any] | None = None,
    identity: Any = None,
    cancellation_token: Any = None,
    cancellation_coordinator: Any = None,
    context: ConnectorRequestContext | None = None,
) -> ConnectorChatCompletionsRequest:
    domain = (
        request
        if isinstance(request, CanonicalChatRequest)
        else CanonicalChatRequest.model_validate(request.model_dump())
    )
    return ConnectorChatCompletionsRequest(
        request=domain,
        processed_messages=processed_messages,
        effective_model=effective_model,
        identity=identity,
        cancellation_token=cancellation_token,
        cancellation_coordinator=cancellation_coordinator,
        context=context,
        options=dict(options or {}),
    )


def attach_gemini_non_streaming_httpx_mocks(client: Any, mock_response: Mock) -> None:
    """Gemini non-streaming uses ``build_request`` + ``send``, not ``post``."""
    mock_request = Mock()
    client.build_request = Mock(return_value=mock_request)
    mock_response.aread = AsyncMock(return_value=b"")
    client.send = AsyncMock(return_value=mock_response)
