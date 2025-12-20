"""Tests for backend request manager context translation."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
    StructuredOutputContext,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_request_manager.context_translation import (
    build_middleware_context,
)


class TestBuildMiddlewareContext:
    """Tests for build_middleware_context helper function."""

    def test_non_streaming_minimal_context(self) -> None:
        """Test building minimal non-streaming middleware context."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        processing_context = ResponseProcessingContext(
            session_id="session-123",
            original_request=request,
        )
        response = ResponseEnvelope(content="response")
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["session_id"] == "session-123"
        assert result["original_request"] == request
        assert result["backend_response"] == response
        assert result["model_name"] == "gpt-4"
        assert "client_os" not in result
        assert "stream_id" not in result

    def test_non_streaming_with_backend_name_from_processing_context(self) -> None:
        """Test backend_name from processing_context takes precedence."""
        processing_context = ResponseProcessingContext(
            session_id="session-123",
            backend_name="anthropic",
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = ResponseEnvelope(content="response")
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["backend_name"] == "anthropic"

    def test_non_streaming_backend_name_fallback_to_extra_body(self) -> None:
        """Test backend_name fallback to extra_body.backend_type."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"backend_type": "openai"},
        )
        response = ResponseEnvelope(content="response")
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["backend_name"] == "openai"

    def test_non_streaming_backend_name_fallback_to_model(self) -> None:
        """Test backend_name fallback to request.model when extra_body missing."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = ResponseEnvelope(content="response")
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        # When backend_name is not in processing_context and extra_body is None,
        # it falls back to model name
        assert result.get("backend_name") == "gpt-4"

    def test_non_streaming_model_name_from_processing_context(self) -> None:
        """Test model_name from processing_context takes precedence."""
        processing_context = ResponseProcessingContext(
            session_id="session-123",
            model_name="claude-3-5-sonnet",
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = ResponseEnvelope(content="response")
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["model_name"] == "claude-3-5-sonnet"

    def test_non_streaming_model_name_fallback_to_request(self) -> None:
        """Test model_name fallback to request.model."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = ResponseEnvelope(content="response")
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["model_name"] == "gpt-4"

    def test_non_streaming_with_structured_output(self) -> None:
        """Test structured output context keys are included."""
        structured_output = StructuredOutputContext(
            schema={"type": "object"},
            schema_name="test_schema",
            request_id="req-123",
        )
        processing_context = ResponseProcessingContext(
            session_id="session-123",
            structured_output=structured_output,
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = ResponseEnvelope(content="response")
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["response_schema"] == {"type": "object"}
        assert result["schema_name"] == "test_schema"
        assert result["request_id"] == "req-123"

    def test_non_streaming_merges_processing_context_values(self) -> None:
        """Test that processing_context.values are merged into result."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = ResponseEnvelope(content="response")
        processing_values = ProcessingContext(
            values={
                "custom_key": "custom_value",
                "another_key": 42,
            }
        )
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=processing_values,
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["custom_key"] == "custom_value"
        assert result["another_key"] == 42

    def test_non_streaming_typed_fields_override_processing_context(self) -> None:
        """Test that typed fields take precedence over processing_context values."""
        processing_context = ResponseProcessingContext(
            session_id="session-123",
            backend_name="anthropic",
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = ResponseEnvelope(content="response")
        processing_values = ProcessingContext(
            values={
                "backend_name": "openai",  # Should be overridden
                "session_id": "other-session",  # Should be overridden
            }
        )
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=processing_values,
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["backend_name"] == "anthropic"  # From processing_context
        assert result["session_id"] == "session-123"  # From processing_context

    def test_streaming_includes_client_os(self) -> None:
        """Test streaming context includes client_os."""
        processing_context = ResponseProcessingContext(
            session_id="session-123",
            client_os="linux",
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = StreamingResponseEnvelope(content=MagicMock())
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=True,
        )

        assert result["client_os"] == "linux"
        assert "stream_id" in result

    def test_streaming_client_os_fallback_to_processing_context(self) -> None:
        """Test client_os fallback to processing_context.values."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = StreamingResponseEnvelope(content=MagicMock())
        processing_values = ProcessingContext(values={"client_os": "windows"})
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=processing_values,
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=True,
        )

        assert result["client_os"] == "windows"

    def test_streaming_includes_stream_id(self) -> None:
        """Test streaming context includes stream_id."""
        structured_output = StructuredOutputContext(
            schema={"type": "object"},
            schema_name="test",
            request_id="req-123",
        )
        processing_context = ResponseProcessingContext(
            session_id="session-123",
            structured_output=structured_output,
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = StreamingResponseEnvelope(content=MagicMock())
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=True,
        )

        assert result["stream_id"] == "req-123"  # From structured_output.request_id

    def test_streaming_stream_id_fallback_to_session_id(self) -> None:
        """Test stream_id fallback to session_id when request_id not available."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = StreamingResponseEnvelope(content=MagicMock())
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=True,
        )

        assert result["stream_id"] == "session-123"

    def test_streaming_structured_output_from_processing_context_values(self) -> None:
        """Test structured output keys extracted from processing_context.values."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = StreamingResponseEnvelope(content=MagicMock())
        processing_values = ProcessingContext(
            values={
                "response_schema": {"type": "object"},
                "schema_name": "test_schema",
                "request_id": "req-456",
            }
        )
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=processing_values,
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=True,
        )

        assert result["response_schema"] == {"type": "object"}
        assert result["schema_name"] == "test_schema"
        assert result["request_id"] == "req-456"
        assert result["stream_id"] == "req-456"  # Uses request_id

    def test_none_response_envelope(self) -> None:
        """Test that None response_envelope is handled gracefully."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=None,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["session_id"] == "session-123"
        assert "backend_response" not in result

    def test_none_processing_context(self) -> None:
        """Test that None processing_context is handled gracefully."""
        processing_context = ResponseProcessingContext(session_id="session-123")
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        response = ResponseEnvelope(content="response")
        request_context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=None,
        )

        result = build_middleware_context(
            processing_context=processing_context,
            request=request,
            response_envelope=response,
            request_context=request_context,
            is_streaming=False,
        )

        assert result["session_id"] == "session-123"
        assert result["backend_response"] == response
