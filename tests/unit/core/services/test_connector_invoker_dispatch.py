"""Unit tests for ConnectorInvoker canonical/legacy dispatch and streaming."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.connector_invoker import ConnectorInvoker

from tests.unit.core.services.connector_invoker_test_support import (
    MockCanonicalBackend,
    MockLegacyBackend,
)

pytest_plugins = ("tests.unit.core.services.connector_invoker_test_support",)


class TestCanonicalBackendDispatch:
    """Tests for canonical backend dispatch."""

    @pytest.mark.asyncio
    async def test_canonical_backend_dispatch(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
        sample_identity: IAppIdentityConfig,
        sample_session_key: SessionKey,
        sample_cancellation_coordinator: ISessionCancellationCoordinator,
        sample_options: dict[str, Any],
    ) -> None:
        """Test that canonical backend is invoked correctly."""
        backend = MockCanonicalBackend()
        domain_request = sample_canonical_request

        result = await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=domain_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=sample_identity,
            cancellation_token=sample_session_key,
            cancellation_coordinator=sample_cancellation_coordinator,
            context=sample_request_context,
            options=sample_options,
        )

        assert backend.chat_completions_called
        assert backend.received_request is not None
        assert backend.received_request.request == domain_request
        assert backend.received_request.processed_messages == list(
            sample_canonical_request.messages
        )
        assert backend.received_request.effective_model == "gpt-4"
        assert backend.received_request.identity == sample_identity
        assert backend.received_request.cancellation_token == sample_session_key
        assert (
            backend.received_request.cancellation_coordinator
            == sample_cancellation_coordinator
        )
        assert backend.received_request.context is not None
        assert backend.received_request.context.request_id == "req-123"
        assert backend.received_request.options == sample_options
        assert isinstance(result, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_canonical_backend_never_receives_dicts(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
    ) -> None:
        """Test that canonical backend never receives dict payloads."""
        backend = MockCanonicalBackend()
        domain_request = sample_canonical_request

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=domain_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=sample_request_context,
            options={},
        )

        # Verify request is a CanonicalChatRequest, not a dict
        assert backend.received_request is not None
        assert isinstance(backend.received_request.request, CanonicalChatRequest)
        # Verify processed_messages are ChatMessage objects, not dicts
        for msg in backend.received_request.processed_messages:
            assert isinstance(msg, ChatMessage)


class TestLegacyBackendDispatch:
    """Tests for legacy backend dispatch."""

    @pytest.mark.asyncio
    async def test_legacy_backend_dispatch(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_options: dict[str, Any],
    ) -> None:
        """Test that legacy backend is invoked correctly."""
        backend = MockLegacyBackend()
        domain_request = sample_canonical_request

        result = await connector_invoker.invoke(
            backend=backend,
            domain_request=domain_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=sample_options,
        )

        assert backend.chat_completions_called
        assert backend.received_kwargs["request_data"] == domain_request
        assert backend.received_kwargs["processed_messages"] == list(
            sample_canonical_request.messages
        )
        assert backend.received_kwargs["effective_model"] == "gpt-4"
        assert backend.received_kwargs["option1"] == "value1"
        assert backend.received_kwargs["option2"] == 42
        assert isinstance(result, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_legacy_backend_never_receives_dicts(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that legacy backend never receives dict payloads."""
        backend = MockLegacyBackend()
        domain_request = sample_canonical_request

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=domain_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        # Verify request_data is a CanonicalChatRequest, not a dict
        assert isinstance(backend.received_kwargs["request_data"], CanonicalChatRequest)
        assert not isinstance(backend.received_kwargs["request_data"], dict)
        # Verify processed_messages are ChatMessage objects, not dicts
        for msg in backend.received_kwargs["processed_messages"]:
            assert isinstance(msg, ChatMessage)

    @pytest.mark.asyncio
    async def test_legacy_backend_options_expansion(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that options are expanded into kwargs for legacy backend."""
        backend = MockLegacyBackend()
        domain_request = sample_canonical_request

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=domain_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={"option1": "value1", "option2": 42},
        )

        assert backend.received_kwargs["option1"] == "value1"
        assert backend.received_kwargs["option2"] == 42


class TestLegacyPathLogging:
    """Tests for legacy path logging."""

    @pytest.mark.asyncio
    async def test_legacy_path_logs_when_used(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that legacy path usage is logged."""
        backend = MockLegacyBackend()
        domain_request = sample_canonical_request

        with caplog.at_level(logging.INFO):
            await connector_invoker.invoke(
                backend=backend,
                domain_request=domain_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        # Verify legacy path was logged
        assert any(
            "Using legacy connector API" in record.message for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_canonical_path_does_not_log_legacy(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that canonical path does not log legacy message."""
        backend = MockCanonicalBackend()
        domain_request = sample_canonical_request

        with caplog.at_level(logging.INFO):
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=domain_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=sample_request_context,
                options={},
            )

        # Verify legacy path was NOT logged
        assert not any(
            "Using legacy connector API" in record.message for record in caplog.records
        )


class TestErrorPropagation:
    """Tests for error propagation."""

    @pytest.mark.asyncio
    async def test_canonical_backend_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that errors from canonical backend are propagated."""
        backend = MockCanonicalBackend()
        domain_request = sample_canonical_request

        async def error_chat_completions(
            request: ConnectorChatCompletionsRequest,
        ) -> ResponseEnvelope | StreamingResponseEnvelope:
            raise ValueError("Test error")

        backend.chat_completions = error_chat_completions  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="Test error"):
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=domain_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

    @pytest.mark.asyncio
    async def test_legacy_backend_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that errors from legacy backend are propagated."""
        backend = MockLegacyBackend()
        domain_request = sample_canonical_request

        async def error_chat_completions(
            *args: Any, **kwargs: Any
        ) -> ResponseEnvelope | StreamingResponseEnvelope:
            raise ValueError("Test error")

        backend.chat_completions = error_chat_completions  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="Test error"):
            await connector_invoker.invoke(
                backend=backend,
                domain_request=domain_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )


class TestStreamingResponse:
    """Tests for streaming response handling."""

    @pytest.mark.asyncio
    async def test_canonical_backend_streaming_response(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that streaming responses from canonical backend are returned."""
        backend = MockCanonicalBackend()
        streaming_response = StreamingResponseEnvelope(
            content=AsyncMock(),
            media_type="text/event-stream",
            headers={},
        )

        async def streaming_chat_completions(
            request: ConnectorChatCompletionsRequest,
        ) -> StreamingResponseEnvelope:
            return streaming_response

        backend.chat_completions = streaming_chat_completions  # type: ignore[method-assign]

        result = await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        assert isinstance(result, StreamingResponseEnvelope)
        assert result == streaming_response

    @pytest.mark.asyncio
    async def test_legacy_backend_streaming_response(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that streaming responses from legacy backend are returned."""
        backend = MockLegacyBackend()
        streaming_response = StreamingResponseEnvelope(
            content=AsyncMock(),
            media_type="text/event-stream",
            headers={},
        )

        async def streaming_chat_completions(
            *args: Any, **kwargs: Any
        ) -> StreamingResponseEnvelope:
            return streaming_response

        backend.chat_completions = streaming_chat_completions  # type: ignore[method-assign]

        result = await connector_invoker.invoke(
            backend=backend,
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        assert isinstance(result, StreamingResponseEnvelope)
        assert result == streaming_response
