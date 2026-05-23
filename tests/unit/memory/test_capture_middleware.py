"""Unit tests for MemoryCaptureMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.memory.capture_middleware import MemoryCaptureMiddleware


def create_mock_memory_service(
    *,
    available: bool = True,
    enabled: bool = True,
    capture_success: bool = True,
) -> MagicMock:
    """Create a mock memory service."""
    service = MagicMock()
    service.is_available.return_value = available
    service.is_enabled_for_session = AsyncMock(return_value=enabled)
    service.capture_interaction = AsyncMock(return_value=capture_success)
    return service


def create_mock_request(
    messages: list | None = None, model: str = "gpt-4o"
) -> MagicMock:
    """Create a mock chat request."""
    if messages is None:
        messages = []

    request = MagicMock()
    request.messages = messages
    request.model = model
    return request


def create_mock_message(role: str, content: str) -> MagicMock:
    """Create a mock chat message."""
    msg = MagicMock()
    msg.role = role
    msg.content = content
    return msg


class TestMemoryCaptureMiddleware:
    """Tests for MemoryCaptureMiddleware."""

    @pytest.mark.asyncio
    async def test_capture_request_skips_when_unavailable(self) -> None:
        """Test that capture is skipped when memory unavailable."""
        service = create_mock_memory_service(available=False)
        middleware = MemoryCaptureMiddleware(service)

        request = create_mock_request([create_mock_message("user", "Hello")])
        await middleware.capture_request("session-1", request)

        service.capture_interaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_capture_request_skips_when_disabled(self) -> None:
        """Test that capture is skipped when session not enabled."""
        service = create_mock_memory_service(enabled=False)
        middleware = MemoryCaptureMiddleware(service)

        request = create_mock_request([create_mock_message("user", "Hello")])
        await middleware.capture_request("session-1", request)

        service.capture_interaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_capture_request_captures_user_messages(self) -> None:
        """Test that user messages are captured."""
        service = create_mock_memory_service()
        middleware = MemoryCaptureMiddleware(service)

        messages = [
            create_mock_message("system", "You are helpful"),
            create_mock_message("user", "What is Python?"),
        ]
        request = create_mock_request(messages, model="gpt-4o")
        await middleware.capture_request("session-1", request)

        # Should only capture user message
        assert service.capture_interaction.call_count == 1
        call_args = service.capture_interaction.call_args
        assert call_args[0][0] == "session-1"
        interaction = call_args[0][1]
        assert interaction.role == "user"
        assert interaction.content == "What is Python?"

    @pytest.mark.asyncio
    async def test_capture_request_ignores_system_messages(self) -> None:
        """Test that system messages are not captured."""
        service = create_mock_memory_service()
        middleware = MemoryCaptureMiddleware(service)

        messages = [create_mock_message("system", "System prompt")]
        request = create_mock_request(messages)
        await middleware.capture_request("session-1", request)

        service.capture_interaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_capture_response_skips_when_unavailable(self) -> None:
        """Test that response capture skips when unavailable."""
        service = create_mock_memory_service(available=False)
        middleware = MemoryCaptureMiddleware(service)

        await middleware.capture_response("session-1", "Response content")

        service.capture_interaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_capture_response_captures_content(self) -> None:
        """Test that response content is captured."""
        service = create_mock_memory_service()
        middleware = MemoryCaptureMiddleware(service)

        await middleware.capture_response(
            "session-1",
            "Python is a programming language.",
            backend="openai",
            model="gpt-4o",
            tokens_used=15,
        )

        assert service.capture_interaction.call_count == 1
        call_args = service.capture_interaction.call_args
        interaction = call_args[0][1]
        assert interaction.role == "assistant"
        assert interaction.content == "Python is a programming language."
        assert interaction.metadata["backend"] == "openai"
        assert interaction.metadata["model"] == "gpt-4o"
        assert interaction.metadata["tokens_used"] == 15

    @pytest.mark.asyncio
    async def test_capture_response_skips_empty_content(self) -> None:
        """Test that empty responses are not captured."""
        service = create_mock_memory_service()
        middleware = MemoryCaptureMiddleware(service)

        await middleware.capture_response("session-1", "")

        service.capture_interaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_capture_response_captures_tool_calls(self) -> None:
        """Test that tool calls are captured in metadata."""
        service = create_mock_memory_service()
        middleware = MemoryCaptureMiddleware(service)

        tool_calls = [{"name": "read_file", "args": {"path": "test.py"}}]
        await middleware.capture_response(
            "session-1",
            "",
            tool_calls=tool_calls,
        )

        assert service.capture_interaction.call_count == 1
        call_args = service.capture_interaction.call_args
        interaction = call_args[0][1]
        assert interaction.metadata["tool_calls"] == tool_calls

    @pytest.mark.asyncio
    async def test_extract_multimodal_content(self) -> None:
        """Test content extraction from multimodal messages."""
        service = create_mock_memory_service()
        middleware = MemoryCaptureMiddleware(service)

        # Create message with list content
        msg = MagicMock()
        msg.role = "user"
        msg.content = [
            {"text": "Part 1"},
            {"type": "image_url", "image_url": {"url": "..."}},
            {"text": "Part 2"},
        ]

        request = create_mock_request([msg])
        await middleware.capture_request("session-1", request)

        call_args = service.capture_interaction.call_args
        interaction = call_args[0][1]
        assert "Part 1" in interaction.content
        assert "Part 2" in interaction.content
