"""Unit tests for ContextInjectionMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.memory.injection_middleware import ContextInjectionMiddleware


def create_mock_memory_service(
    *,
    available: bool = True,
    enabled: bool = True,
    user_id: str | None = "user-1",
    project_root: str | None = "/project",
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> MagicMock:
    """Create a mock memory service."""
    service = MagicMock()
    service.is_available.return_value = available
    service.is_enabled_for_session = AsyncMock(return_value=enabled)
    service.get_session_user_id = AsyncMock(return_value=user_id)
    service.get_session_project_root = AsyncMock(return_value=project_root)
    # Create mock session state
    session_state = MagicMock()
    session_state.tenant_id = tenant_id
    session_state.project_id = project_id
    service.get_session_state = AsyncMock(return_value=session_state)
    return service


def create_mock_context_injector(context: dict | None = None) -> MagicMock:
    """Create a mock context injector."""
    injector = MagicMock()
    injector.get_context_for_session = AsyncMock(return_value=context)
    injector.format_context_for_injection = MagicMock(
        return_value="Formatted context" if context else None
    )
    return injector


def create_mock_config(require_project: bool = False) -> MagicMock:
    """Create a mock memory config."""
    config = MagicMock()
    config.require_project_discovery = require_project
    return config


def create_mock_request(messages: list | None = None) -> MagicMock:
    """Create a mock chat request."""
    if messages is None:
        messages = []

    request = MagicMock()
    request.messages = messages
    request.model_copy = MagicMock(return_value=request)
    return request


def create_mock_message(role: str, content: str) -> MagicMock:
    """Create a mock chat message."""
    msg = MagicMock()
    msg.role = role
    msg.content = content
    return msg


class TestContextInjectionMiddleware:
    """Tests for ContextInjectionMiddleware."""

    @pytest.mark.asyncio
    async def test_skips_when_unavailable(self) -> None:
        """Test that injection is skipped when memory unavailable."""
        service = create_mock_memory_service(available=False)
        injector = create_mock_context_injector({"summaries": []})
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        request = create_mock_request([create_mock_message("user", "Hello")])
        result = await middleware.maybe_inject_context("session-1", request)

        injector.get_context_for_session.assert_not_called()
        assert result is request

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self) -> None:
        """Test that injection is skipped when session not enabled."""
        service = create_mock_memory_service(enabled=False)
        injector = create_mock_context_injector({"summaries": []})
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        request = create_mock_request([create_mock_message("user", "Hello")])
        result = await middleware.maybe_inject_context("session-1", request)

        injector.get_context_for_session.assert_not_called()
        assert result is request

    @pytest.mark.asyncio
    async def test_skips_when_no_user_id(self) -> None:
        """Test that injection is skipped when no user_id."""
        service = create_mock_memory_service(user_id=None)
        injector = create_mock_context_injector({"summaries": []})
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        request = create_mock_request([create_mock_message("user", "Hello")])
        result = await middleware.maybe_inject_context("session-1", request)

        injector.get_context_for_session.assert_not_called()
        assert result is request

    @pytest.mark.asyncio
    async def test_skips_when_project_required_but_missing(self) -> None:
        """Test that injection is skipped when project required but missing."""
        service = create_mock_memory_service(project_root=None)
        injector = create_mock_context_injector({"summaries": []})
        config = create_mock_config(require_project=True)
        middleware = ContextInjectionMiddleware(service, injector, config)

        request = create_mock_request([create_mock_message("user", "Hello")])
        result = await middleware.maybe_inject_context("session-1", request)

        injector.get_context_for_session.assert_not_called()
        assert result is request

    @pytest.mark.asyncio
    async def test_injects_context_when_available(self) -> None:
        """Test that context is injected when available."""
        service = create_mock_memory_service()
        injector = create_mock_context_injector({"summaries": ["summary"]})
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        messages = [
            create_mock_message("system", "You are helpful"),
            create_mock_message("user", "What is Python?"),
        ]
        request = create_mock_request(messages)
        await middleware.maybe_inject_context("session-1", request)

        injector.get_context_for_session.assert_called_once()
        request.model_copy.assert_called_once()

    @pytest.mark.asyncio
    async def test_only_injects_once_per_session(self) -> None:
        """Test that context is only injected once per session."""
        service = create_mock_memory_service()
        injector = create_mock_context_injector({"summaries": ["summary"]})
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        request = create_mock_request([create_mock_message("user", "First")])

        await middleware.maybe_inject_context("session-1", request)
        await middleware.maybe_inject_context("session-1", request)

        # Should only call build_context once
        assert injector.get_context_for_session.call_count == 1

    @pytest.mark.asyncio
    async def test_different_sessions_get_injection(self) -> None:
        """Test that different sessions each get injection."""
        service = create_mock_memory_service()
        injector = create_mock_context_injector({"summaries": ["summary"]})
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        request = create_mock_request([create_mock_message("user", "Hello")])

        await middleware.maybe_inject_context("session-1", request)
        await middleware.maybe_inject_context("session-2", request)

        assert injector.get_context_for_session.call_count == 2

    @pytest.mark.asyncio
    async def test_injects_marker_when_no_context(self) -> None:
        """Test that marker is injected when no relevant context (per Req 8.11)."""
        service = create_mock_memory_service()
        # When context is None, format_context_for_injection returns marker
        injector = create_mock_context_injector(None)
        injector.format_context_for_injection.return_value = (
            "[NO_PRIOR_CONTEXT_PROVIDED]"
        )
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        request = create_mock_request([create_mock_message("user", "Hello")])
        await middleware.maybe_inject_context("session-1", request)

        # Per Req 8.11: Marker should still be injected
        injector.format_context_for_injection.assert_called()
        request.model_copy.assert_called_once()

    def test_clear_session_allows_reinjection(self) -> None:
        """Test that clearing a session allows re-injection."""
        service = create_mock_memory_service()
        injector = create_mock_context_injector({"summaries": ["summary"]})
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        # Simulate injection happened
        middleware._injected_sessions.add("session-1")

        middleware.clear_session("session-1")

        assert "session-1" not in middleware._injected_sessions

    @pytest.mark.asyncio
    async def test_extracts_first_user_prompt(self) -> None:
        """Test extraction of first user prompt."""
        service = create_mock_memory_service()
        injector = create_mock_context_injector({"summaries": ["summary"]})
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        messages = [
            create_mock_message("system", "System"),
            create_mock_message("user", "First user message"),
            create_mock_message("user", "Second user message"),
        ]
        request = create_mock_request(messages)

        await middleware.maybe_inject_context("session-1", request)

        # get_context_for_session should receive the first user message
        call_args = injector.get_context_for_session.call_args
        assert call_args.kwargs["current_prompt"] == "First user message"

    @pytest.mark.asyncio
    async def test_handles_injection_error_gracefully(self) -> None:
        """Test that injection errors don't break the request."""
        service = create_mock_memory_service()
        injector = create_mock_context_injector({"summaries": ["summary"]})
        injector.get_context_for_session = AsyncMock(
            side_effect=Exception("Test error")
        )
        config = create_mock_config()
        middleware = ContextInjectionMiddleware(service, injector, config)

        request = create_mock_request([create_mock_message("user", "Hello")])
        result = await middleware.maybe_inject_context("session-1", request)

        # Should return original request on error
        assert result is request
