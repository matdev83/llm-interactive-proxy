"""Tests for backend request manager context models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
    StructuredOutputContext,
    ToolCallRetryState,
)
from src.core.domain.chat import ChatMessage, ChatRequest


class TestStructuredOutputContext:
    """Tests for StructuredOutputContext model."""

    def test_create_with_required_fields(self) -> None:
        """Test creating StructuredOutputContext with all required fields."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        context = StructuredOutputContext(
            schema=schema,
            schema_name="test_schema",
            request_id="req-123",
        )
        assert context.schema == schema
        assert context.schema_name == "test_schema"
        assert context.request_id == "req-123"

    def test_validation_requires_all_fields(self) -> None:
        """Test that all fields are required."""
        with pytest.raises(ValidationError):
            StructuredOutputContext(schema={}, schema_name="test")  # type: ignore[call-overload]

        with pytest.raises(ValidationError):
            StructuredOutputContext(schema={}, request_id="req-123")  # type: ignore[call-overload]

        with pytest.raises(ValidationError):
            StructuredOutputContext(schema_name="test", request_id="req-123")  # type: ignore[call-overload]


class TestResponseProcessingContext:
    """Tests for ResponseProcessingContext model."""

    def test_create_with_minimal_fields(self) -> None:
        """Test creating ResponseProcessingContext with only required fields."""
        context = ResponseProcessingContext(session_id="session-123")
        assert context.session_id == "session-123"
        assert context.backend_name is None
        assert context.model_name is None
        assert context.client_os is None
        assert context.original_request is None
        assert context.structured_output is None

    def test_create_with_all_fields(self) -> None:
        """Test creating ResponseProcessingContext with all fields."""
        schema_context = StructuredOutputContext(
            schema={"type": "object"},
            schema_name="test",
            request_id="req-123",
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        context = ResponseProcessingContext(
            session_id="session-123",
            backend_name="openai",
            model_name="gpt-4",
            client_os="linux",
            original_request=request,
            structured_output=schema_context,
        )
        assert context.session_id == "session-123"
        assert context.backend_name == "openai"
        assert context.model_name == "gpt-4"
        assert context.client_os == "linux"
        assert context.original_request == request
        assert context.structured_output == schema_context

    def test_validation_requires_session_id(self) -> None:
        """Test that session_id is required."""
        with pytest.raises(ValidationError):
            ResponseProcessingContext()  # type: ignore[call-overload]


class TestToolCallRetryState:
    """Tests for ToolCallRetryState model."""

    def test_create_with_required_fields(self) -> None:
        """Test creating ToolCallRetryState with required fields."""
        state = ToolCallRetryState(
            retry_count=1,
            max_retries=3,
        )
        assert state.retry_count == 1
        assert state.max_retries == 3
        assert state.steering_message is None
        assert state.is_streaming is False

    def test_create_with_all_fields(self) -> None:
        """Test creating ToolCallRetryState with all fields."""
        state = ToolCallRetryState(
            retry_count=2,
            max_retries=3,
            steering_message="Do not repeat blocked tool call",
            is_streaming=True,
        )
        assert state.retry_count == 2
        assert state.max_retries == 3
        assert state.steering_message == "Do not repeat blocked tool call"
        assert state.is_streaming is True

    def test_validation_requires_retry_count_and_max_retries(self) -> None:
        """Test that retry_count and max_retries are required."""
        with pytest.raises(ValidationError):
            ToolCallRetryState(retry_count=1)  # type: ignore[call-overload]

        with pytest.raises(ValidationError):
            ToolCallRetryState(max_retries=3)  # type: ignore[call-overload]

    def test_validation_enforces_non_negative_counts(self) -> None:
        """Test that retry_count and max_retries must be non-negative."""
        # Valid: zero is allowed
        state = ToolCallRetryState(retry_count=0, max_retries=0)
        assert state.retry_count == 0
        assert state.max_retries == 0

        # Invalid: negative values
        with pytest.raises(ValidationError):
            ToolCallRetryState(retry_count=-1, max_retries=3)

        with pytest.raises(ValidationError):
            ToolCallRetryState(retry_count=1, max_retries=-1)

    def test_serialization(self) -> None:
        """Test that models can be serialized to dict."""
        state = ToolCallRetryState(
            retry_count=1,
            max_retries=3,
            steering_message="test",
            is_streaming=False,
        )
        data = state.model_dump()
        assert data["retry_count"] == 1
        assert data["max_retries"] == 3
        assert data["steering_message"] == "test"
        assert data["is_streaming"] is False
