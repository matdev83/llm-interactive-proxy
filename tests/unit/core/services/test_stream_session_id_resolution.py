"""
Unit tests for StreamSessionIdResolver.

This module tests the unified session-id resolution behavior provided by StreamSessionIdResolver.
It ensures that the resolution precedence rules are correctly applied.
"""

from unittest.mock import Mock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.services.stream_session_id_resolver import StreamSessionIdResolver


@pytest.fixture
def resolver():
    """Create a StreamSessionIdResolver instance."""
    return StreamSessionIdResolver()


class TestPrecedence:
    """Test resolution precedence rules (1 to 5)."""

    def test_precedence_1_session_id_parameter(self, resolver):
        """Test that session_id parameter has highest precedence."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            session_id="request-session",
            extra_body={"session_id": "extra-session"},
        )
        context = Mock(spec=RequestContext)
        context.request_id = "context-request-id"

        result = resolver.resolve_stream_session_id("param-session", context, request)

        # Parameter session_id should win
        assert result == "param-session"

    def test_precedence_2_request_session_id(self, resolver):
        """Test that request.session_id is second in precedence."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            session_id="request-session",
            extra_body={"session_id": "extra-session"},
        )
        context = Mock(spec=RequestContext)
        context.request_id = "context-request-id"

        result = resolver.resolve_stream_session_id(None, context, request)

        # request.session_id should win
        assert result == "request-session"

    def test_precedence_3_extra_body_session_id(self, resolver):
        """Test that extra_body.session_id is third in precedence."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"session_id": "extra-session"},
        )
        context = Mock(spec=RequestContext)
        context.request_id = "context-request-id"

        result = resolver.resolve_stream_session_id(None, context, request)

        # extra_body.session_id should win
        assert result == "extra-session"

    def test_precedence_4_context_request_id(self, resolver):
        """Test that context.request_id is fourth in precedence."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )
        context = Mock(spec=RequestContext)
        context.request_id = "context-request-id"

        result = resolver.resolve_stream_session_id(None, context, request)

        # context.request_id should win
        assert result == "context-request-id"

    def test_precedence_5_uuid_fallback(self, resolver):
        """Test UUID fallback when all sources are empty."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )

        result = resolver.resolve_stream_session_id(None, None, request)

        # Should generate UUID (32 hex characters)
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)


class TestEdgeCases:
    """Test edge cases in session ID resolution."""

    def test_empty_string_treated_as_missing(self, resolver):
        """Test that empty strings are treated as missing."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            session_id="",  # Empty string
        )
        context = Mock(spec=RequestContext)
        context.request_id = "context-request-id"

        result = resolver.resolve_stream_session_id("", context, request)

        # Should skip empty strings and use context.request_id
        assert result == "context-request-id"

    def test_none_context_handled(self, resolver):
        """Test that None context is handled gracefully."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )

        result = resolver.resolve_stream_session_id(None, None, request)

        # Should generate UUID
        assert len(result) == 32

    def test_missing_extra_body_handled(self, resolver):
        """Test that missing extra_body is handled gracefully."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            extra_body=None,
        )
        context = Mock(spec=RequestContext)
        context.request_id = "context-request-id"

        result = resolver.resolve_stream_session_id(None, context, request)

        # Should use context.request_id
        assert result == "context-request-id"

    def test_request_none_handled(self, resolver):
        """Test that None request is handled gracefully (BufferedWireCapture case)."""
        context = Mock(spec=RequestContext)
        context.request_id = "context-request-id"

        # BufferedWireCapture might call without request
        result = resolver.resolve_stream_session_id(None, context, None)

        # Should use context.request_id
        assert result == "context-request-id"
