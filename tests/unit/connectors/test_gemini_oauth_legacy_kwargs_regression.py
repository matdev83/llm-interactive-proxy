"""Contract tests for ``GeminiOAuthBaseConnector.chat_completions`` entry shape."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope


class DummyGeminiOAuthConnector(GeminiOAuthBaseConnector):
    """Minimal concrete subclass for testing ``GeminiOAuthBaseConnector``."""

    backend_type = "gemini-oauth-test"

    def __init__(self) -> None:  # -- intentional no-op stub
        self._credential_validation_errors: list[str] = []
        self._model_registry: MagicMock | None = None
        self._public_to_internal_model_map: dict[str, str] = {}
        self.name = self.backend_type
        self._credential_coordinator = None
        self._error_mapper = None

    async def _discover_project_id(self, auth_session: object = None) -> str:
        return "dummy-project"


def _stub_connector_methods(connector: DummyGeminiOAuthConnector) -> Any:
    stub = cast(Any, connector)
    stub._validate_runtime_credentials = AsyncMock(return_value=True)
    stub._ensure_healthy = AsyncMock()
    return stub


def test_chat_completions_signature_is_canonical_only() -> None:
    import inspect

    sig = inspect.signature(DummyGeminiOAuthConnector.chat_completions)
    names = list(sig.parameters.keys())
    assert names == ["self", "request"]
    request_param = sig.parameters["request"]
    assert request_param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD


@pytest.mark.asyncio
async def test_chat_completions_rejects_legacy_kwargs() -> None:
    connector = _stub_connector_methods(DummyGeminiOAuthConnector())
    request_data = CanonicalChatRequest(
        model="gemini-pro",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=False,
    )
    with pytest.raises(TypeError):
        await connector.chat_completions(  # type: ignore[call-arg]
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hi")],
            effective_model="gemini-pro",
        )


@pytest.mark.asyncio
async def test_canonical_request_dispatches_to_canonical_path() -> None:
    connector = _stub_connector_methods(DummyGeminiOAuthConnector())
    mock_canonical = connector._chat_completions_canonical = AsyncMock(
        return_value=ResponseEnvelope(content={"id": "test"}, status_code=200)
    )

    canonical = ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="gemini-pro",
            messages=[ChatMessage(role="user", content="Hi")],
        ),
        processed_messages=[ChatMessage(role="user", content="Hi")],
        effective_model="gemini-pro",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )

    await connector.chat_completions(canonical)

    mock_canonical.assert_called_once()
    assert mock_canonical.call_args[0][0] is canonical


def test_resolve_internal_effective_model_strips_google_vendor_prefix() -> None:
    connector = DummyGeminiOAuthConnector()
    assert (
        connector._resolve_internal_effective_model("google/gemini-3-flash-preview")
        == "gemini-3-flash-preview"
    )


def test_resolve_internal_effective_model_strips_backend_type_prefix() -> None:
    connector = DummyGeminiOAuthConnector()
    assert (
        connector._resolve_internal_effective_model(
            "gemini-oauth-test:google/gemini-3-flash-preview"
        )
        == "gemini-3-flash-preview"
    )
