"""Tests for ToolCallStreamContextResolver.

Following TDD methodology: tests written before implementation.
"""

from __future__ import annotations

from unittest.mock import Mock

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState
from src.core.interfaces.tool_call_stream_context_resolver_interface import (
    IToolCallStreamContextResolver,
)
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
    ToolCallBufferState,
)
from src.core.services.tool_call_reactor.stream_buffer_adapter import (
    StreamBufferAdapter,
)
from src.core.services.tool_call_reactor.stream_context_resolver import (
    ToolCallStreamContextResolver,
)


class TestStreamKeyResolution:
    """Tests for stream key resolution."""

    def test_resolve_stream_key_from_metadata_stream_id(self) -> None:
        """Test that stream_id from metadata takes priority."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(
            content="test",
            metadata={"stream_id": "metadata-stream-123"},
        )
        context = {"stream_id": "context-stream-456"}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        assert stream_key == "metadata-stream-123"

    def test_resolve_stream_key_from_metadata_id(self) -> None:
        """Test that id from metadata is used when stream_id not present."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(
            content="test",
            metadata={"id": "metadata-id-123"},
        )
        context = {"stream_id": "context-stream-456"}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        assert stream_key == "metadata-id-123"

    def test_resolve_stream_key_from_context_stream_id(self) -> None:
        """Test that context stream_id is used when metadata missing."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(content="test", metadata={})
        context = {"stream_id": "context-stream-456"}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        assert stream_key == "context-stream-456"

    def test_resolve_stream_key_from_context_response_stream_id(self) -> None:
        """Test that response_stream_id from context is used."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(content="test", metadata={})
        context = {"response_stream_id": "response-stream-456"}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        assert stream_key == "response-stream-456"

    def test_resolve_stream_key_falls_back_to_session_id(self) -> None:
        """Test that session_id is used when metadata and context missing."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(content="test", metadata={})
        context = {}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        assert stream_key == "session-789"

    def test_resolve_stream_key_falls_back_to_anonymous_stream(self) -> None:
        """Test that anonymous-stream is used when all identifiers missing."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(content="test", metadata={})
        context = {}

        stream_key = resolver.resolve_stream_key("", context, response)

        assert stream_key == "anonymous-stream"

    def test_resolve_stream_key_handles_none_context(self) -> None:
        """Test that None context is handled gracefully."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(content="test", metadata={})

        stream_key = resolver.resolve_stream_key("session-789", None, response)

        assert stream_key == "session-789"

    def test_resolve_stream_key_handles_none_metadata(self) -> None:
        """Test that None metadata is handled gracefully."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(content="test", metadata=None)
        context = {"stream_id": "context-stream-456"}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        assert stream_key == "context-stream-456"

    def test_resolve_stream_key_handles_non_dict_metadata(self) -> None:
        """Test that non-dict metadata is handled gracefully."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        # Create a mock response with non-dict metadata
        response = Mock()
        response.metadata = "not-a-dict"
        context = {"stream_id": "context-stream-456"}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        assert stream_key == "context-stream-456"

    def test_resolve_stream_key_handles_non_string_candidates(self) -> None:
        """Test that non-string candidates are skipped."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(
            content="test",
            metadata={"stream_id": 12345},  # Non-string
        )
        context = {"stream_id": "context-stream-456"}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        # Should skip non-string metadata and use context
        assert stream_key == "context-stream-456"

    def test_resolve_stream_key_handles_empty_string_candidates(self) -> None:
        """Test that empty string candidates are skipped."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        response = ProcessedResponse(
            content="test",
            metadata={"stream_id": ""},  # Empty string
        )
        context = {"stream_id": "context-stream-456"}

        stream_key = resolver.resolve_stream_key("session-789", context, response)

        # Should skip empty string and use context
        assert stream_key == "context-stream-456"


class TestBufferStateResolution:
    """Tests for buffer state resolution."""

    def test_resolve_buffer_state_from_context_tool_call_buffer_state(self) -> None:
        """Test that tool_call_buffer_state from context is used first."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        buffer_state = ToolCallBufferState()
        context = {"tool_call_buffer_state": buffer_state}
        stream_key = "test-stream"

        result = resolver.resolve_buffer_state(context, stream_key)

        assert result is not None
        assert isinstance(result, IToolCallBufferState)
        assert isinstance(result, StreamBufferAdapter)
        # Verify it wraps the original buffer state
        assert result._buffer_state is buffer_state

    def test_resolve_buffer_state_from_registry(self) -> None:
        """Test that registry is used when context doesn't have buffer state."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        context = {"stream_id": "test-stream-123"}
        stream_key = "test-stream-123"

        result = resolver.resolve_buffer_state(context, stream_key)

        assert result is not None
        assert isinstance(result, IToolCallBufferState)
        assert isinstance(result, StreamBufferAdapter)
        # Verify registry was accessed
        buffer_from_registry = registry.get_tool_call_buffer(stream_key)
        assert result._buffer_state is buffer_from_registry

    def test_resolve_buffer_state_uses_stream_identifier_from_context(self) -> None:
        """Test that stream identifier from context is used for registry lookup."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        context = {"stream_id": "context-stream-id"}
        stream_key = "fallback-stream-key"

        result = resolver.resolve_buffer_state(context, stream_key)

        assert result is not None
        # Should use context stream_id, not stream_key
        buffer_from_registry = registry.get_tool_call_buffer("context-stream-id")
        assert result._buffer_state is buffer_from_registry

    def test_resolve_buffer_state_uses_response_stream_id_from_context(self) -> None:
        """Test that response_stream_id from context is used."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        context = {"response_stream_id": "response-stream-id"}
        stream_key = "fallback-stream-key"

        result = resolver.resolve_buffer_state(context, stream_key)

        assert result is not None
        buffer_from_registry = registry.get_tool_call_buffer("response-stream-id")
        assert result._buffer_state is buffer_from_registry

    def test_resolve_buffer_state_falls_back_to_stream_key(self) -> None:
        """Test that stream_key is used when context identifiers missing."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        context = {}
        stream_key = "fallback-stream-key"

        result = resolver.resolve_buffer_state(context, stream_key)

        assert result is not None
        buffer_from_registry = registry.get_tool_call_buffer(stream_key)
        assert result._buffer_state is buffer_from_registry

    def test_resolve_buffer_state_returns_none_for_anonymous_stream(self) -> None:
        """Test that None is returned for anonymous-stream (degraded mode)."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        context = {}
        stream_key = "anonymous-stream"

        result = resolver.resolve_buffer_state(context, stream_key)

        assert result is None

    def test_resolve_buffer_state_returns_none_for_none_context(self) -> None:
        """Test that None context returns None (degraded mode)."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        stream_key = "test-stream"

        result = resolver.resolve_buffer_state(None, stream_key)

        assert result is None

    def test_resolve_buffer_state_handles_registry_exception(self) -> None:
        """Test that registry exceptions are handled gracefully."""
        # Create a mock registry that raises exceptions
        mock_registry = Mock(spec=StreamingContextRegistry)
        mock_registry.get_tool_call_buffer = Mock(
            side_effect=Exception("Registry error")
        )

        resolver = ToolCallStreamContextResolver(mock_registry)

        context = {"stream_id": "test-stream"}
        stream_key = "test-stream"

        result = resolver.resolve_buffer_state(context, stream_key)

        # Should return None gracefully without crashing
        assert result is None

    def test_resolve_buffer_state_skips_non_toolcallbufferstate_in_context(
        self,
    ) -> None:
        """Test that non-ToolCallBufferState values in context are skipped."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        context = {"tool_call_buffer_state": "not-a-buffer-state"}
        stream_key = "test-stream"

        result = resolver.resolve_buffer_state(context, stream_key)

        # Should fall back to registry lookup
        assert result is not None
        assert isinstance(result, StreamBufferAdapter)
        buffer_from_registry = registry.get_tool_call_buffer(stream_key)
        assert result._buffer_state is buffer_from_registry

    def test_resolve_buffer_state_handles_empty_string_stream_identifier(self) -> None:
        """Test that empty string stream identifiers are handled."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        context = {"stream_id": ""}
        stream_key = "test-stream"

        result = resolver.resolve_buffer_state(context, stream_key)

        # Should use stream_key fallback
        assert result is not None
        buffer_from_registry = registry.get_tool_call_buffer(stream_key)
        assert result._buffer_state is buffer_from_registry


class TestResolverInterface:
    """Tests for interface compliance."""

    def test_resolver_implements_interface(self) -> None:
        """Test that resolver implements IToolCallStreamContextResolver."""
        registry = StreamingContextRegistry()
        resolver = ToolCallStreamContextResolver(registry)

        assert isinstance(resolver, IToolCallStreamContextResolver)
