"""Shared helpers for OpenRouter connector unit tests."""

from __future__ import annotations

from typing import Any

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.interfaces.configuration_interface import IAppIdentityConfig


def openrouter_connector_chat_request(
    request_data: ChatRequest,
    *,
    processed_messages: list[ChatMessage],
    effective_model: str,
    key_name: str,
    api_key: str,
    openrouter_api_base_url: str | None = None,
    identity: IAppIdentityConfig | None = None,
    extra_options: dict[str, Any] | None = None,
) -> ConnectorChatCompletionsRequest:
    """Build :class:`ConnectorChatCompletionsRequest` for :meth:`OpenRouterBackend.chat_completions`."""
    options: dict[str, Any] = {"key_name": key_name, "api_key": api_key}
    if openrouter_api_base_url is not None:
        options["openrouter_api_base_url"] = openrouter_api_base_url
    if extra_options:
        options.update(extra_options)
    return ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest.model_validate(request_data.model_dump()),
        processed_messages=processed_messages,
        effective_model=effective_model,
        identity=identity,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options=options,
    )
