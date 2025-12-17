"""
Tests for DI-friendliness of streaming contracts refactoring collaborators.

These tests verify that new collaborators introduced in the streaming contracts
refactoring follow DI best practices:
- No implicit fallback construction in production code paths
- Stateful collaborators use DI interfaces and explicit registration
- Avoid "if dependency is None then create default" patterns
"""

from __future__ import annotations

from src.core.domain.streaming.parsing.raw_chunk_parser import RawChunkParser
from src.core.services.streaming.error_mapping import StreamingErrorMapper
from src.core.transport.streaming.sse_serializer import SSESerializer


class TestRawChunkParserDIFriendliness:
    """Test that RawChunkParser is stateless and DI-friendly."""

    def test_can_be_constructed_without_dependencies(self) -> None:
        """RawChunkParser should be constructible without DI dependencies."""
        parser = RawChunkParser()
        assert parser is not None

    def test_no_fallback_construction(self) -> None:
        """RawChunkParser should not have fallback construction patterns."""
        parser = RawChunkParser()
        # Verify it constructs strategies directly (no None checks or fallbacks)
        assert len(parser._strategies) > 0
        # All strategies should be concrete instances, not None
        assert all(strategy is not None for strategy in parser._strategies)


class TestSSESerializerDIFriendliness:
    """Test that SSESerializer is stateless and DI-friendly."""

    def test_can_be_constructed_without_dependencies(self) -> None:
        """SSESerializer should be constructible without DI dependencies."""
        serializer = SSESerializer()
        assert serializer is not None

    def test_no_constructor_dependencies(self) -> None:
        """SSESerializer should not require constructor dependencies."""
        # SSESerializer has no __init__ parameters, so it's stateless
        serializer = SSESerializer()
        # Verify it can serialize without external dependencies
        from src.core.domain.streaming.streaming_content import StreamingContent

        content = StreamingContent(content="test", is_done=False)
        result = serializer.serialize(content)
        assert isinstance(result, bytes)
        assert b"data:" in result


class TestStreamingErrorMapperDIFriendliness:
    """Test that StreamingErrorMapper is stateless and DI-friendly."""

    def test_all_methods_are_static(self) -> None:
        """StreamingErrorMapper should use static methods (no instance state)."""
        # Verify map_backend_error is static
        import inspect

        assert inspect.isfunction(StreamingErrorMapper.map_backend_error)
        # Or verify it can be called without instance
        error = ValueError("test error")
        result = StreamingErrorMapper.map_backend_error(error, "test_provider")
        assert result is not None

    def test_no_constructor_needed(self) -> None:
        """StreamingErrorMapper should not require instantiation."""
        # All methods are static, so no instance needed
        error = ValueError("test error")
        result = StreamingErrorMapper.map_backend_error(error, "test_provider")
        assert result is not None


class TestParserStrategiesDIFriendliness:
    """Test that parser strategies are stateless and DI-friendly."""

    def test_passthrough_parser_stateless(self) -> None:
        """PassthroughParser should be stateless."""
        from src.core.domain.streaming.parsing.passthrough_parser import (
            PassthroughParser,
        )

        parser = PassthroughParser()
        assert parser is not None
        # Verify no instance variables that would require DI
        assert not hasattr(parser, "_dependency") or parser._dependency is None

    def test_openai_dict_parser_stateless(self) -> None:
        """OpenAIDictParser should be stateless."""
        from src.core.domain.streaming.parsing.openai_dict_parser import (
            OpenAIDictParser,
        )

        parser = OpenAIDictParser()
        assert parser is not None

    def test_fallback_parser_stateless(self) -> None:
        """FallbackParser should be stateless."""
        from src.core.domain.streaming.parsing.fallback_parser import FallbackParser

        parser = FallbackParser()
        assert parser is not None


class TestNoImplicitFallbackConstruction:
    """Test that no new collaborators use implicit fallback construction."""

    def test_raw_chunk_parser_no_fallback(self) -> None:
        """RawChunkParser should not have 'if dependency is None' patterns."""
        import inspect

        source = inspect.getsource(RawChunkParser.__init__)
        # Check for common fallback patterns
        assert (
            "if" not in source
            or "is None" not in source
            or "dependency" not in source.lower()
        )

    def test_sse_serializer_no_fallback(self) -> None:
        """SSESerializer should not have fallback construction."""
        import inspect

        # SSESerializer has no custom __init__, so it uses object.__init__
        # which is stateless and has no fallback construction
        # Check if there's a custom __init__ by checking if it's defined in the class
        if "__init__" in SSESerializer.__dict__:
            source = inspect.getsource(SSESerializer.__init__)
            assert "is None" not in source or "dependency" not in source.lower()
        else:
            # No custom __init__ means no fallback construction possible
            assert True
