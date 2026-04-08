"""Regression tests for GeminiOAuthBaseConnector backward-compatibility contract.

These tests guard against the 2026-04-07 breakage where the refactored
``GeminiOAuthBaseConnector.chat_completions`` dropped its legacy ``**kwargs``
acceptance, causing ``TypeError`` in all three sibling-repo connectors
(gemini-oauth-auto, gemini-oauth-free, gemini-oauth-plan).

See: post-mortem for "gemini-oauth connectors cease to work" incident.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


class DummyGeminiOAuthConnector(GeminiOAuthBaseConnector):
    """Minimal concrete subclass for testing ``GeminiOAuthBaseConnector``."""

    backend_type = "gemini-oauth-test"

    def __init__(self) -> None:  # -- intentional no-op stub
        self._credential_validation_errors: list[str] = []
        self._model_registry: MagicMock | None = None
        self._public_to_internal_model_map: dict[str, str] = {}
        self.name = self.backend_type

    async def _discover_project_id(self, auth_session: object = None) -> str:
        return "dummy-project"


def _stub_connector_methods(connector: DummyGeminiOAuthConnector) -> Any:
    stub = cast(Any, connector)
    stub._validate_runtime_credentials = AsyncMock(return_value=True)
    stub._ensure_healthy = AsyncMock()
    return stub


class TestGeminiOAuthConnectorLegacyKwargsContract:
    """Guard tests for the legacy ``**kwargs`` calling pattern.

    The sibling repo connectors (gemini_oauth_auto, gemini_oauth_free,
    gemini_oauth_plan) all call ``super().chat_completions`` with the
    legacy per-parameter signature.  This MUST remain supported.
    """

    def test_signature_accepts_request_data_kwarg(self) -> None:
        """``chat_completions`` must accept ``request_data`` as a keyword arg."""
        import inspect

        sig = inspect.signature(GeminiOAuthBaseConnector.chat_completions)
        params = list(sig.parameters.keys())
        assert (
            "**kwargs" in params or "kwargs" in params
        ), f"chat_completions must have **kwargs.  Parameters: {params}"

    def test_signature_accepts_processed_messages_kwarg(self) -> None:
        """``chat_completions`` must accept ``processed_messages`` as a keyword arg."""
        import inspect

        sig = inspect.signature(GeminiOAuthBaseConnector.chat_completions)
        assert "kwargs" in list(
            sig.parameters.keys()
        ), "chat_completions must have **kwargs to accept processed_messages"

    @pytest.mark.asyncio
    async def test_legacy_non_streaming_kwargs_dispatches_internally(self) -> None:
        """Legacy call with ``request_data, processed_messages, effective_model``
        must dispatch to ``_chat_completions_code_assist`` (non-streaming).
        """
        connector = _stub_connector_methods(DummyGeminiOAuthConnector())
        mock_internal = connector._chat_completions_code_assist = AsyncMock(
            return_value=ResponseEnvelope(
                content={"id": "test"},
                status_code=200,
            )
        )

        request_data = CanonicalChatRequest(
            model="gemini-pro",
            messages=[ChatMessage(role="user", content="Hi")],
            stream=False,
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hi")],
            effective_model="gemini-pro",
            context=None,
        )

        mock_internal.assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_streaming_kwargs_dispatches_internally(self) -> None:
        """Legacy call with ``request_data`` having ``stream=True`` must
        dispatch to ``_chat_completions_code_assist_streaming``.
        """
        connector = _stub_connector_methods(DummyGeminiOAuthConnector())
        mock_internal = connector._chat_completions_code_assist_streaming = AsyncMock(
            return_value=StreamingResponseEnvelope(
                content=AsyncMock(),
                media_type="text/event-stream",
                headers={},
            )
        )

        request_data = CanonicalChatRequest(
            model="gemini-pro",
            messages=[ChatMessage(role="user", content="Hi")],
            stream=True,
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hi")],
            effective_model="gemini-pro",
            context=None,
        )

        mock_internal.assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_kwargs_normalizes_vendor_prefixed_model(self) -> None:
        """Legacy kwargs path must strip the vendor prefix before dispatch.

        The sibling oauth-connectors repo passes vendor-prefixed public model names,
        but Code Assist expects the internal model identifier.
        """
        connector = _stub_connector_methods(DummyGeminiOAuthConnector())
        mock_internal = connector._chat_completions_code_assist_streaming = AsyncMock(
            return_value=StreamingResponseEnvelope(
                content=AsyncMock(),
                media_type="text/event-stream",
                headers={},
            )
        )

        request_data = CanonicalChatRequest(
            model="gemini-oauth-plan:google/gemini-3-flash-preview",
            messages=[ChatMessage(role="user", content="Hi")],
            stream=True,
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hi")],
            effective_model="google/gemini-3-flash-preview",
            context=None,
        )

        assert mock_internal.call_args.kwargs["effective_model"] == (
            "gemini-3-flash-preview"
        )

    @pytest.mark.asyncio
    async def test_legacy_kwargs_normalizes_backend_prefixed_model(self) -> None:
        """Legacy kwargs path must strip this backend's public prefix too."""
        connector = _stub_connector_methods(DummyGeminiOAuthConnector())
        mock_internal = connector._chat_completions_code_assist = AsyncMock(
            return_value=ResponseEnvelope(content={"id": "x"}, status_code=200)
        )

        await connector.chat_completions(
            request_data=MagicMock(stream=False),
            processed_messages=[],
            effective_model="gemini-oauth-test:google/gemini-3-flash-preview",
        )

        assert mock_internal.call_args.kwargs["effective_model"] == (
            "gemini-3-flash-preview"
        )

    @pytest.mark.asyncio
    async def test_legacy_kwargs_forwards_context(self) -> None:
        """``context=`` must be forwarded to the internal dispatcher."""
        connector = _stub_connector_methods(DummyGeminiOAuthConnector())
        mock_internal = connector._chat_completions_code_assist = AsyncMock(
            return_value=ResponseEnvelope(
                content={"id": "test"},
                status_code=200,
            )
        )

        ctx = MagicMock(spec=ConnectorRequestContext)
        ctx.session_id = "test-session"

        await connector.chat_completions(
            request_data=MagicMock(stream=False),
            processed_messages=[],
            effective_model="gemini-pro",
            context=ctx,
            some_extra_kwarg="value",
        )

        call_kwargs = mock_internal.call_args.kwargs
        assert call_kwargs["context"] is ctx
        assert call_kwargs["some_extra_kwarg"] == "value"

    @pytest.mark.asyncio
    async def test_legacy_kwargs_forwards_remaining_kwargs(self) -> None:
        """Arbitrary extra kwargs must be forwarded (supports gemini_oauth_free's
        ``api_key``, ``project``, ``openrouter_api_base_url``, etc.).
        """
        connector = _stub_connector_methods(DummyGeminiOAuthConnector())
        mock_internal = connector._chat_completions_code_assist = AsyncMock(
            return_value=ResponseEnvelope(content={"id": "x"}, status_code=200)
        )

        await connector.chat_completions(
            request_data=MagicMock(stream=False),
            processed_messages=[],
            effective_model="gemini-pro",
            api_key="test-key",
            project="my-project",
            openrouter_api_base_url="https://example.com",
            random_provider_option=42,
        )

        call_kwargs = mock_internal.call_args.kwargs
        assert call_kwargs["api_key"] == "test-key"
        assert call_kwargs["project"] == "my-project"
        assert call_kwargs["random_provider_option"] == 42

    @pytest.mark.asyncio
    async def test_canonical_request_dispatches_to_canonical_path(self) -> None:
        """Calling with a ``ConnectorChatCompletionsRequest`` must use the
        canonical ``_chat_completions_canonical`` path.
        """
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
