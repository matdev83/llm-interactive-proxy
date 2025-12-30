"""
Unit tests for ConnectorInvoker.

Tests canonical-first dispatch and legacy fallback following TDD principles.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from src.connectors.base import LLMBackend
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.connector_invoker import ConnectorInvoker


class MockCanonicalBackend:
    """Mock backend implementing ICanonicalChatCompletionsBackend."""

    def __init__(self) -> None:
        self.chat_completions_called = False
        self.received_request: ConnectorChatCompletionsRequest | None = None

    async def chat_completions(
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Mock canonical chat_completions implementation."""
        self.chat_completions_called = True
        self.received_request = request
        return ResponseEnvelope(
            content={"model": request.effective_model, "choices": []},
            headers={},
        )


class MockLegacyBackend(LLMBackend):
    """Mock legacy backend implementing only LLMBackend."""

    def __init__(self) -> None:
        # LLMBackend requires config, but we can pass None/Mock for testing
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        super().__init__(config=mock_config)
        self.chat_completions_called = False
        self.received_kwargs: dict[str, Any] = {}

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: Any | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Mock legacy chat_completions implementation."""
        self.chat_completions_called = True
        self.received_kwargs = {
            "request_data": request_data,
            "processed_messages": processed_messages,
            "effective_model": effective_model,
            "identity": identity,
            "cancellation_token": cancellation_token,
            "cancellation_coordinator": cancellation_coordinator,
            **kwargs,
        }
        return ResponseEnvelope(
            content={"model": effective_model, "choices": []},
            headers={},
        )

    async def initialize(self, **kwargs: Any) -> None:
        """Mock initialize method."""

    def get_available_models(self) -> list[str]:
        """Mock get_available_models method."""
        return []


@pytest.fixture
def connector_invoker() -> ConnectorInvoker:
    """Create a ConnectorInvoker instance."""
    return ConnectorInvoker()


@pytest.fixture
def sample_canonical_request() -> CanonicalChatRequest:
    """Create a sample CanonicalChatRequest."""
    return CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def sample_request_context() -> RequestContext:
    """Create a sample RequestContext."""
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=MagicMock(),
        request_id="req-123",
        session_id="session-456",
        client_host="192.168.1.1",
        extensions={"key1": "value1", "key2": 42},
    )


@pytest.fixture
def sample_identity() -> IAppIdentityConfig:
    """Create a mock identity."""
    identity = Mock(spec=IAppIdentityConfig)
    identity.api_key = "test-key"
    return identity


@pytest.fixture
def sample_session_key() -> SessionKey:
    """Create a sample SessionKey."""
    return SessionKey(protocol="http", primary_id="session-456", group_id=None)


@pytest.fixture
def sample_cancellation_coordinator() -> ISessionCancellationCoordinator:
    """Create a mock cancellation coordinator."""
    return Mock(spec=ISessionCancellationCoordinator)


@pytest.fixture
def sample_options() -> dict[str, Any]:
    """Create sample connector options."""
    return {"option1": "value1", "option2": 42}


class TestContextProjection:
    """Tests for RequestContext → ConnectorRequestContext projection."""

    def test_project_context_with_all_fields(
        self,
        connector_invoker: ConnectorInvoker,
        sample_request_context: RequestContext,
    ) -> None:
        """Test context projection with all fields populated."""
        projected = connector_invoker._project_context(sample_request_context)

        assert projected is not None
        assert projected.request_id == "req-123"
        assert projected.session_id == "session-456"
        assert projected.client_host == "192.168.1.1"
        assert projected.extensions == {"key1": "value1", "key2": 42}

    def test_project_context_with_none_values(
        self,
        connector_invoker: ConnectorInvoker,
    ) -> None:
        """Test context projection with None values."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            request_id=None,
            session_id=None,
            client_host=None,
        )
        projected = connector_invoker._project_context(context)

        assert projected is not None
        assert projected.request_id is None
        assert projected.session_id is None
        assert projected.client_host is None
        assert projected.extensions == {}

    def test_project_context_returns_none_when_context_is_none(
        self,
        connector_invoker: ConnectorInvoker,
    ) -> None:
        """Test that None context returns None projection."""
        projected = connector_invoker._project_context(None)
        assert projected is None

    def test_project_context_copies_extensions(
        self,
        connector_invoker: ConnectorInvoker,
    ) -> None:
        """Test that extensions dict is copied (not shared reference)."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            extensions={"key": "value"},
        )
        projected = connector_invoker._project_context(context)

        assert projected is not None
        assert projected.extensions == {"key": "value"}
        # Modify original - should not affect projected
        context.extensions["new_key"] = "new_value"
        assert projected.extensions == {"key": "value"}


class TestCanonicalRequestBuilding:
    """Tests for building ConnectorChatCompletionsRequest."""

    def test_build_canonical_request_with_all_fields(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
        sample_identity: IAppIdentityConfig,
        sample_session_key: SessionKey,
        sample_cancellation_coordinator: ISessionCancellationCoordinator,
        sample_options: dict[str, Any],
    ) -> None:
        """Test building canonical request with all fields."""
        domain_request = sample_canonical_request
        processed_messages = list(sample_canonical_request.messages)
        effective_model = "gpt-4"
        projected_context = connector_invoker._project_context(sample_request_context)

        connector_request = connector_invoker._build_canonical_request(
            domain_request=domain_request,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=sample_identity,
            cancellation_token=sample_session_key,
            cancellation_coordinator=sample_cancellation_coordinator,
            context=projected_context,
            options=sample_options,
        )

        assert connector_request.request == domain_request
        assert connector_request.processed_messages == processed_messages
        assert connector_request.effective_model == effective_model
        assert connector_request.identity == sample_identity
        assert connector_request.cancellation_token == sample_session_key
        assert connector_request.cancellation_coordinator == sample_cancellation_coordinator
        assert connector_request.context == projected_context
        assert connector_request.options == sample_options

    def test_build_canonical_request_with_minimal_fields(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test building canonical request with minimal fields."""
        domain_request = sample_canonical_request
        processed_messages = list(sample_canonical_request.messages)
        effective_model = "gpt-4"

        connector_request = connector_invoker._build_canonical_request(
            domain_request=domain_request,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        assert connector_request.request == domain_request
        assert connector_request.processed_messages == processed_messages
        assert connector_request.effective_model == effective_model
        assert connector_request.identity is None
        assert connector_request.cancellation_token is None
        assert connector_request.cancellation_coordinator is None
        assert connector_request.context is None
        assert connector_request.options == {}


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
        """Test that canonical backend receives canonical request."""
        backend = MockCanonicalBackend()
        domain_request = sample_canonical_request
        processed_messages = list(sample_canonical_request.messages)
        effective_model = "gpt-4"

        result = await connector_invoker.invoke(
            backend=backend,
            domain_request=domain_request,
            canonical_request=sample_canonical_request,
            effective_model=effective_model,
            identity=sample_identity,
            cancellation_token=sample_session_key,
            cancellation_coordinator=sample_cancellation_coordinator,
            context=sample_request_context,
            options=sample_options,
        )

        assert backend.chat_completions_called
        assert backend.received_request is not None
        assert backend.received_request.request == domain_request
        assert backend.received_request.processed_messages == processed_messages
        assert backend.received_request.effective_model == effective_model
        assert backend.received_request.identity == sample_identity
        assert backend.received_request.cancellation_token == sample_session_key
        assert backend.received_request.cancellation_coordinator == sample_cancellation_coordinator
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
            backend=backend,
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
        sample_request_context: RequestContext,
        sample_identity: IAppIdentityConfig,
        sample_session_key: SessionKey,
        sample_cancellation_coordinator: ISessionCancellationCoordinator,
        sample_options: dict[str, Any],
    ) -> None:
        """Test that legacy backend receives typed domain models."""
        backend = MockLegacyBackend()
        domain_request = sample_canonical_request
        list(sample_canonical_request.messages)
        effective_model = "gpt-4"

        result = await connector_invoker.invoke(
            backend=backend,
            domain_request=domain_request,
            canonical_request=sample_canonical_request,
            effective_model=effective_model,
            identity=sample_identity,
            cancellation_token=sample_session_key,
            cancellation_coordinator=sample_cancellation_coordinator,
            context=sample_request_context,
            options=sample_options,
        )

        assert backend.chat_completions_called
        # Verify legacy backend receives canonical domain model, not dict
        assert isinstance(backend.received_kwargs["request_data"], CanonicalChatRequest)
        assert backend.received_kwargs["request_data"] == domain_request
        # Verify processed_messages are typed ChatMessage objects
        assert isinstance(backend.received_kwargs["processed_messages"], list)
        for msg in backend.received_kwargs["processed_messages"]:
            assert isinstance(msg, ChatMessage)
        assert backend.received_kwargs["effective_model"] == effective_model
        assert backend.received_kwargs["identity"] == sample_identity
        assert backend.received_kwargs["cancellation_token"] == sample_session_key
        assert backend.received_kwargs["cancellation_coordinator"] == sample_cancellation_coordinator
        # Verify options are expanded into kwargs
        assert backend.received_kwargs["option1"] == "value1"
        assert backend.received_kwargs["option2"] == 42
        assert isinstance(result, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_legacy_backend_never_receives_dicts(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
    ) -> None:
        """Test that legacy backend never receives dict payloads."""
        backend = MockLegacyBackend()
        domain_request = sample_canonical_request

        await connector_invoker.invoke(
            backend=backend,
            domain_request=domain_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=sample_request_context,
            options={},
        )

        # Verify request_data is a CanonicalChatRequest, not a dict
        assert isinstance(backend.received_kwargs["request_data"], CanonicalChatRequest)
        assert not isinstance(backend.received_kwargs["request_data"], dict)
        # Verify processed_messages are ChatMessage objects, not dicts
        for msg in backend.received_kwargs["processed_messages"]:
            assert isinstance(msg, ChatMessage)
            assert not isinstance(msg, dict)

    @pytest.mark.asyncio
    async def test_legacy_backend_options_expansion(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_options: dict[str, Any],
    ) -> None:
        """Test that options are expanded into kwargs for legacy backend."""
        backend = MockLegacyBackend()

        await connector_invoker.invoke(
            backend=backend,
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=sample_options,
        )

        # Verify options are expanded into kwargs
        assert "option1" in backend.received_kwargs
        assert "option2" in backend.received_kwargs
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
        """Test that legacy path logs at INFO level."""
        backend = MockLegacyBackend()

        with caplog.at_level(logging.INFO):
            await connector_invoker.invoke(
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

        # Check that legacy path was logged
        log_messages = [record.message for record in caplog.records]
        legacy_logged = any("legacy" in msg.lower() for msg in log_messages)
        assert legacy_logged, "Legacy path should be logged"

    @pytest.mark.asyncio
    async def test_canonical_path_does_not_log_legacy(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that canonical path does not log legacy message."""
        backend = MockCanonicalBackend()

        with caplog.at_level(logging.INFO):
            await connector_invoker.invoke(
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

        # Check that legacy path was not logged
        log_messages = [record.message for record in caplog.records]
        legacy_logged = any("legacy" in msg.lower() for msg in log_messages)
        assert not legacy_logged, "Canonical path should not log legacy message"


class TestErrorPropagation:
    """Tests for error propagation from both paths."""

    @pytest.mark.asyncio
    async def test_canonical_backend_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that errors from canonical backend propagate."""
        backend = MockCanonicalBackend()
        error = ValueError("Canonical backend error")

        async def failing_chat_completions(
            request: ConnectorChatCompletionsRequest,
        ) -> ResponseEnvelope:
            raise error

        backend.chat_completions = failing_chat_completions

        with pytest.raises(ValueError, match="Canonical backend error"):
            await connector_invoker.invoke(
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

    @pytest.mark.asyncio
    async def test_legacy_backend_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that errors from legacy backend propagate."""
        backend = MockLegacyBackend()
        error = ValueError("Legacy backend error")

        async def failing_chat_completions(*args: Any, **kwargs: Any) -> ResponseEnvelope:
            raise error

        backend.chat_completions = failing_chat_completions

        with pytest.raises(ValueError, match="Legacy backend error"):
            await connector_invoker.invoke(
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

        backend.chat_completions = streaming_chat_completions

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

        async def streaming_chat_completions(*args: Any, **kwargs: Any) -> StreamingResponseEnvelope:
            return streaming_response

        backend.chat_completions = streaming_chat_completions

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
