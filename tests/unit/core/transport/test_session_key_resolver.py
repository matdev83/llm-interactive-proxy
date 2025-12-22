"""Tests for session key resolution utilities."""

from __future__ import annotations

import pytest
from src.core.domain.request_context import RequestContext
from src.core.transport.session_key_resolver import (
    create_codebuff_session_key,
    resolve_session_key_from_request_context,
)


class TestResolveSessionKeyFromRequestContext:
    """Tests for resolving SessionKey from RequestContext."""

    def test_resolves_with_request_id_and_conversation_header(self) -> None:
        """Test resolution with request_id and x-conversation-id header."""
        context = RequestContext(
            headers={"x-conversation-id": "conv-123"},
            cookies={},
            state={},
            app_state=None,
            request_id="trace-abc",
        )

        result = resolve_session_key_from_request_context(context)

        assert result is not None
        assert result.protocol == "http"
        assert result.primary_id == "trace-abc"
        assert result.group_id == "conv-123"

    def test_resolves_with_request_id_only(self) -> None:
        """Test resolution with request_id but no conversation_id."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="trace-xyz",
        )

        result = resolve_session_key_from_request_context(context)

        assert result is not None
        assert result.protocol == "http"
        assert result.primary_id == "trace-xyz"
        assert result.group_id is None

    def test_returns_none_when_request_id_missing(self) -> None:
        """Test that None is returned when request_id is missing."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id=None,
        )

        result = resolve_session_key_from_request_context(context)

        assert result is None

    def test_returns_none_when_request_id_empty(self) -> None:
        """Test that None is returned when request_id is empty."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="",
        )

        result = resolve_session_key_from_request_context(context)

        assert result is None

    def test_returns_none_when_context_is_none(self) -> None:
        """Test that None is returned when context is None."""
        result = resolve_session_key_from_request_context(None)

        assert result is None

    def test_strips_whitespace_from_request_id(self) -> None:
        """Test that whitespace is stripped from request_id."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="  trace-abc  ",
        )

        result = resolve_session_key_from_request_context(context)

        assert result is not None
        assert result.primary_id == "trace-abc"

    def test_extracts_conversation_id_from_domain_request(self) -> None:
        """Test extraction of conversation_id from domain_request extra_body."""
        from src.core.domain.chat import ChatMessage, ChatRequest

        domain_request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"conversation_id": "conv-from-request"},
        )

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="trace-abc",
            domain_request=domain_request,
        )

        result = resolve_session_key_from_request_context(context)

        assert result is not None
        assert result.group_id == "conv-from-request"

    def test_prefers_header_over_domain_request(self) -> None:
        """Test that header conversation_id takes precedence over domain_request."""
        from src.core.domain.chat import ChatMessage, ChatRequest

        domain_request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"conversation_id": "conv-from-request"},
        )

        context = RequestContext(
            headers={"x-conversation-id": "conv-from-header"},
            cookies={},
            state={},
            app_state=None,
            request_id="trace-abc",
            domain_request=domain_request,
        )

        result = resolve_session_key_from_request_context(context)

        assert result is not None
        assert result.group_id == "conv-from-header"


class TestCreateCodebuffSessionKey:
    """Tests for creating Codebuff SessionKey."""

    def test_creates_session_key_with_codebuff_prefix(self) -> None:
        """Test that SessionKey is created with codebuff: prefix."""
        result = create_codebuff_session_key("client-session-123")

        assert result.protocol == "codebuff"
        assert result.primary_id == "codebuff:client-session-123"
        assert result.group_id is None

    def test_strips_whitespace_from_session_id(self) -> None:
        """Test that whitespace is stripped from client_session_id."""
        result = create_codebuff_session_key("  client-session-123  ")

        assert result.primary_id == "codebuff:client-session-123"

    def test_raises_on_empty_session_id(self) -> None:
        """Test that ValueError is raised for empty session_id."""
        with pytest.raises(ValueError, match="cannot be empty"):
            create_codebuff_session_key("")

    def test_raises_on_none_session_id(self) -> None:
        """Test that ValueError is raised for None session_id."""
        with pytest.raises(ValueError):
            create_codebuff_session_key(None)  # type: ignore[arg-type]
