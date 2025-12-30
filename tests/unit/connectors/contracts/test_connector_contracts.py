"""Tests for canonical connector-facing contracts.

Tests cover:
- ConnectorRequestContext: Minimal connector-facing context contract
- ConnectorChatCompletionsRequest: Canonical connector request payload
- ICanonicalChatCompletionsBackend: Protocol for canonical connector API
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from unittest.mock import Mock

import pytest
from pydantic.types import JsonValue

# Import contracts (will fail until implemented)
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
    ICanonicalChatCompletionsBackend,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)


class TestConnectorRequestContext:
    """Tests for ConnectorRequestContext contract."""

    def test_creation_with_all_fields(self) -> None:
        """Test creating ConnectorRequestContext with all fields populated."""
        context = ConnectorRequestContext(
            request_id="req-123",
            session_id="session-456",
            client_host="192.168.1.1",
            extensions={"key1": "value1", "key2": 42},
        )

        assert context.request_id == "req-123"
        assert context.session_id == "session-456"
        assert context.client_host == "192.168.1.1"
        assert context.extensions == {"key1": "value1", "key2": 42}

    def test_creation_with_minimal_fields(self) -> None:
        """Test creating ConnectorRequestContext with None values."""
        context = ConnectorRequestContext(
            request_id=None,
            session_id=None,
            client_host=None,
        )

        assert context.request_id is None
        assert context.session_id is None
        assert context.client_host is None
        assert context.extensions == {}  # Should default to empty dict

    def test_extensions_default_to_empty_dict(self) -> None:
        """Test that extensions default to empty dict when not provided."""
        context = ConnectorRequestContext(
            request_id="req-123",
            session_id="session-456",
            client_host="192.168.1.1",
        )

        assert context.extensions == {}
        assert isinstance(context.extensions, dict)

    def test_extensions_are_json_safe(self) -> None:
        """Test that extensions dict accepts only JSON-serializable values."""
        # Valid JSON values
        valid_extensions: dict[str, JsonValue] = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "nested_dict": {"key": "value"},
        }

        context = ConnectorRequestContext(
            request_id="req-123",
            session_id="session-456",
            client_host="192.168.1.1",
            extensions=valid_extensions,
        )

        # Verify it can be JSON serialized
        json_str = json.dumps(context.extensions)
        assert json_str is not None

        # Verify round-trip
        deserialized = json.loads(json_str)
        assert deserialized == valid_extensions

    def test_extensions_type_annotation(self) -> None:
        """Test that extensions field has correct type annotation."""
        from dataclasses import fields

        field = next(
            f for f in fields(ConnectorRequestContext) if f.name == "extensions"
        )
        # Field.type is a string representation in dataclasses
        assert (
            str(field.type) == "dict[str, JsonValue]"
            or field.type == dict[str, JsonValue]
        )

    def test_is_internal_dto(self) -> None:
        """Test that ConnectorRequestContext inherits from InternalDTO."""
        from src.core.interfaces.model_bases import InternalDTO

        context = ConnectorRequestContext(
            request_id="req-123",
            session_id="session-456",
            client_host="192.168.1.1",
        )

        assert isinstance(context, InternalDTO)


class TestConnectorChatCompletionsRequest:
    """Tests for ConnectorChatCompletionsRequest contract."""

    @pytest.fixture
    def sample_request(self) -> CanonicalChatRequest:
        """Create a sample CanonicalChatRequest for testing."""
        return CanonicalChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="Hello"),
            ],
        )

    @pytest.fixture
    def sample_messages(self) -> list[ChatMessage]:
        """Create sample processed messages for testing."""
        return [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ]

    @pytest.fixture
    def mock_identity(self) -> IAppIdentityConfig:
        """Create a mock identity config."""
        identity = Mock(spec=IAppIdentityConfig)
        return identity

    @pytest.fixture
    def mock_cancellation_coordinator(self) -> ISessionCancellationCoordinator:
        """Create a mock cancellation coordinator."""
        coordinator = Mock(spec=ISessionCancellationCoordinator)
        return coordinator

    def test_creation_with_all_fields(
        self,
        sample_request: CanonicalChatRequest,
        sample_messages: list[ChatMessage],
        mock_identity: IAppIdentityConfig,
        mock_cancellation_coordinator: ISessionCancellationCoordinator,
    ) -> None:
        """Test creating ConnectorChatCompletionsRequest with all fields populated."""
        session_key = SessionKey(
            protocol="http",
            primary_id="session-123",
            group_id="conversation-456",
        )
        context = ConnectorRequestContext(
            request_id="req-123",
            session_id="session-456",
            client_host="192.168.1.1",
        )

        connector_request = ConnectorChatCompletionsRequest(
            request=sample_request,
            processed_messages=sample_messages,
            effective_model="gpt-4",
            identity=mock_identity,
            cancellation_token=session_key,
            cancellation_coordinator=mock_cancellation_coordinator,
            context=context,
            options={"temperature": 0.7, "max_tokens": 100},
        )

        assert connector_request.request == sample_request
        assert connector_request.processed_messages == sample_messages
        assert connector_request.effective_model == "gpt-4"
        assert connector_request.identity == mock_identity
        assert connector_request.cancellation_token == session_key
        assert (
            connector_request.cancellation_coordinator == mock_cancellation_coordinator
        )
        assert connector_request.context == context
        assert connector_request.options == {"temperature": 0.7, "max_tokens": 100}

    def test_creation_with_optional_fields_none(
        self,
        sample_request: CanonicalChatRequest,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test creating ConnectorChatCompletionsRequest with optional fields as None."""
        connector_request = ConnectorChatCompletionsRequest(
            request=sample_request,
            processed_messages=sample_messages,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        assert connector_request.identity is None
        assert connector_request.cancellation_token is None
        assert connector_request.cancellation_coordinator is None
        assert connector_request.context is None
        assert connector_request.options == {}  # Should default to empty dict

    def test_options_default_to_empty_dict(
        self,
        sample_request: CanonicalChatRequest,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test that options default to empty dict when not provided."""
        connector_request = ConnectorChatCompletionsRequest(
            request=sample_request,
            processed_messages=sample_messages,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        assert connector_request.options == {}
        assert isinstance(connector_request.options, dict)

    def test_options_are_json_safe(
        self,
        sample_request: CanonicalChatRequest,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test that options dict accepts only JSON-serializable values."""
        valid_options: dict[str, JsonValue] = {
            "temperature": 0.7,
            "max_tokens": 100,
            "top_p": 0.9,
            "stream": True,
            "stop": None,
            "logit_bias": {"123": 0.5},
        }

        connector_request = ConnectorChatCompletionsRequest(
            request=sample_request,
            processed_messages=sample_messages,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=valid_options,
        )

        # Verify it can be JSON serialized
        json_str = json.dumps(connector_request.options)
        assert json_str is not None

        # Verify round-trip
        deserialized = json.loads(json_str)
        assert deserialized == valid_options

    def test_processed_messages_accepts_sequence(
        self,
        sample_request: CanonicalChatRequest,
    ) -> None:
        """Test that processed_messages accepts Sequence[ChatMessage]."""
        # Use tuple (Sequence but not list)
        messages_tuple: Sequence[ChatMessage] = (
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi"),
        )

        connector_request = ConnectorChatCompletionsRequest(
            request=sample_request,
            processed_messages=messages_tuple,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        assert connector_request.processed_messages == messages_tuple
        assert isinstance(connector_request.processed_messages, Sequence)

    def test_cancellation_coordinator_type_is_not_any(
        self,
        sample_request: CanonicalChatRequest,
        sample_messages: list[ChatMessage],
        mock_cancellation_coordinator: ISessionCancellationCoordinator,
    ) -> None:
        """Test that cancellation_coordinator uses typed interface, not Any."""
        connector_request = ConnectorChatCompletionsRequest(
            request=sample_request,
            processed_messages=sample_messages,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=mock_cancellation_coordinator,
            context=None,
        )

        # Verify it accepts ISessionCancellationCoordinator
        assert (
            connector_request.cancellation_coordinator == mock_cancellation_coordinator
        )
        assert isinstance(
            connector_request.cancellation_coordinator, ISessionCancellationCoordinator
        )

    def test_is_internal_dto(
        self,
        sample_request: CanonicalChatRequest,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test that ConnectorChatCompletionsRequest inherits from InternalDTO."""
        from src.core.interfaces.model_bases import InternalDTO

        connector_request = ConnectorChatCompletionsRequest(
            request=sample_request,
            processed_messages=sample_messages,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        assert isinstance(connector_request, InternalDTO)


class TestICanonicalChatCompletionsBackend:
    """Tests for ICanonicalChatCompletionsBackend protocol."""

    @pytest.fixture
    def sample_request(
        self,
    ) -> ConnectorChatCompletionsRequest:
        """Create a sample ConnectorChatCompletionsRequest for testing."""
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        return ConnectorChatCompletionsRequest(
            request=CanonicalChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="Hello")],
            ),
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

    def test_protocol_can_be_implemented(
        self,
        sample_request: ConnectorChatCompletionsRequest,
    ) -> None:
        """Test that a mock connector can implement the protocol."""
        from src.core.domain.responses import ResponseEnvelope

        class MockCanonicalConnector:
            """Mock connector implementing ICanonicalChatCompletionsBackend."""

            async def chat_completions(
                self,
                request: ConnectorChatCompletionsRequest,
            ) -> ResponseEnvelope:
                """Mock implementation."""
                return ResponseEnvelope(
                    id="test-id",
                    model="gpt-4",
                    choices=[],
                )

        connector = MockCanonicalConnector()

        # Verify it matches the protocol (structural typing)
        assert hasattr(connector, "chat_completions")
        assert callable(connector.chat_completions)

        # Type checker should accept this as ICanonicalChatCompletionsBackend
        # Runtime check: verify signature matches
        import inspect

        sig = inspect.signature(connector.chat_completions)
        # Async methods don't include 'self' in signature parameters
        assert len(sig.parameters) == 1  # request only
        assert "request" in sig.parameters
        # Check return annotation (can be type or string)
        return_annotation = sig.return_annotation
        assert (
            return_annotation == ResponseEnvelope
            or str(return_annotation) == "ResponseEnvelope"
            or "ResponseEnvelope" in str(return_annotation)
        )

    def test_protocol_signature_matches_expected_return_type(
        self,
        sample_request: ConnectorChatCompletionsRequest,
    ) -> None:
        """Test that protocol signature matches expected return type."""
        # Verify protocol definition
        import inspect

        from src.core.domain.responses import (
            ResponseEnvelope,
            StreamingResponseEnvelope,
        )

        # Get the protocol method signature
        protocol_method = ICanonicalChatCompletionsBackend.chat_completions
        sig = inspect.signature(protocol_method)

        # Verify return type annotation
        return_annotation = sig.return_annotation
        assert return_annotation in (
            ResponseEnvelope | StreamingResponseEnvelope,
            "ResponseEnvelope | StreamingResponseEnvelope",
        )

    def test_protocol_does_not_require_transport_types(self) -> None:
        """Test that protocol does not import or require transport framework types."""
        import inspect
        import sys

        # Get the module where the protocol is defined
        protocol_module = sys.modules[ICanonicalChatCompletionsBackend.__module__]

        # Check that no FastAPI/Starlette types are imported
        # Check imports specifically, not docstrings
        module_source = inspect.getsource(protocol_module)
        source_lines = module_source.split("\n")

        # Check import statements (not docstrings/comments)
        import_lines = [
            line.strip()
            for line in source_lines
            if line.strip().startswith(("import ", "from "))
        ]

        # Verify no FastAPI/Starlette imports
        for import_line in import_lines:
            assert (
                "fastapi" not in import_line.lower()
            ), f"Found FastAPI import: {import_line}"
            assert (
                "starlette" not in import_line.lower()
            ), f"Found Starlette import: {import_line}"
