"""Shared mocks and fixtures for ConnectorInvoker unit tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from src.connectors.base import LLMBackend
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
        mock_config = MagicMock()
        super().__init__(config=mock_config)
        self.chat_completions_called = False
        self.received_kwargs: dict[str, Any] = {}

    async def chat_completions(  # type: ignore[override]
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
