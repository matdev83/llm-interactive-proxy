"""Unit tests for SSO sandbox handler.

Tests the SandboxHandler class that generates restricted responses
for unauthenticated users.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.auth.sso.sandbox_handler import SandboxHandler


class TestSandboxHandler:
    """Test suite for SandboxHandler."""

    def test_init(self) -> None:
        """Test SandboxHandler initialization."""
        auth_url = "https://example.com/auth/login"
        handler = SandboxHandler(auth_url)

        assert handler.auth_url == auth_url

    @pytest.mark.asyncio
    async def test_generate_login_banner_uses_default_url(self) -> None:
        """Test that generate_login_banner uses default auth URL."""
        auth_url = "https://example.com/auth/login"
        handler = SandboxHandler(auth_url)

        response = await handler.generate_login_banner()

        # Verify auth URL is in the message
        message_content = response["choices"][0]["message"]["content"]
        assert auth_url in message_content

    @pytest.mark.asyncio
    async def test_generate_login_banner_uses_override_url(self) -> None:
        """Test that generate_login_banner uses override auth URL."""
        default_url = "https://example.com/auth/login"
        override_url = "https://other.com/sso/auth"
        handler = SandboxHandler(default_url)

        response = await handler.generate_login_banner(override_url)

        # Verify override URL is in the message
        message_content = response["choices"][0]["message"]["content"]
        assert override_url in message_content
        assert default_url not in message_content

    @pytest.mark.asyncio
    async def test_generate_login_banner_response_structure(self) -> None:
        """Test that login banner has correct OpenAI response structure."""
        handler = SandboxHandler("https://example.com/auth")
        response = await handler.generate_login_banner()

        # Verify top-level structure
        assert "id" in response
        assert "object" in response
        assert "created" in response
        assert "model" in response
        assert "choices" in response
        assert "usage" in response

        # Verify object type
        assert response["object"] == "chat.completion"

        # Verify choices structure
        assert len(response["choices"]) == 1
        choice = response["choices"][0]
        assert choice["index"] == 0
        assert "message" in choice
        assert "finish_reason" in choice
        assert choice["finish_reason"] == "stop"

        # Verify message structure
        message = choice["message"]
        assert message["role"] == "assistant"
        assert "content" in message
        assert len(message["content"]) > 0

        # Verify usage structure
        usage = response["usage"]
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 0
        assert usage["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_generate_login_banner_contains_required_instructions(self) -> None:
        """Test that login banner contains all required instructions."""
        handler = SandboxHandler("https://example.com/auth")
        response = await handler.generate_login_banner()

        message_content = response["choices"][0]["message"]["content"]

        # Verify key instruction elements
        assert "Authentication Required" in message_content
        assert "authenticate" in message_content.lower()
        assert "token" in message_content.lower()
        assert "agent" in message_content.lower()
        assert "browser" in message_content.lower()

    @pytest.mark.asyncio
    async def test_generate_login_banner_warns_about_session_continuation(self) -> None:
        """Test that login banner warns about session continuation."""
        handler = SandboxHandler("https://example.com/auth")
        response = await handler.generate_login_banner()

        message_content = response["choices"][0]["message"]["content"]

        # Verify warning about session continuation
        assert "cannot continue" in message_content.lower()

    def test_format_as_completion_response_basic(self) -> None:
        """Test basic message formatting as completion response."""
        handler = SandboxHandler("https://example.com/auth")
        message = "Test message"

        response = handler.format_as_completion_response(message)

        # Verify message content
        assert response["choices"][0]["message"]["content"] == message

        # Verify response structure
        assert response["object"] == "chat.completion"
        assert response["model"] == "sandbox"
        assert response["id"] == "chatcmpl-sandbox"

    def test_format_as_completion_response_json_serializable(self) -> None:
        """Test that formatted response is JSON serializable."""
        handler = SandboxHandler("https://example.com/auth")
        message = "Test message with special chars: \n\t\r"

        response = handler.format_as_completion_response(message)

        # Should not raise exception
        json_str = json.dumps(response)
        deserialized = json.loads(json_str)

        assert deserialized == response

    def test_detect_sandbox_history_empty_list(self) -> None:
        """Test sandbox detection with empty message list."""
        handler = SandboxHandler("https://example.com/auth")

        result = handler.detect_sandbox_history([])

        assert result is False

    def test_detect_sandbox_history_no_sandbox_content(self) -> None:
        """Test sandbox detection with regular messages."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is False

    def test_detect_sandbox_history_with_authentication_required_header(
        self,
    ) -> None:
        """Test sandbox detection with 'Authentication Required' header."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": "# Authentication Required\nPlease authenticate.",
            },
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is True

    def test_detect_sandbox_history_with_welcome_message(self) -> None:
        """Test sandbox detection with welcome message."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {
                "role": "assistant",
                "content": "Welcome to the LLM Proxy with SSO authentication.",
            }
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is True

    def test_detect_sandbox_history_with_sandbox_id(self) -> None:
        """Test sandbox detection with sandbox completion ID."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {
                "role": "assistant",
                "content": "Some message",
                "id": "chatcmpl-sandbox",
            }
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is True

    @pytest.mark.asyncio
    async def test_detect_sandbox_history_with_full_sandbox_response(self) -> None:
        """Test sandbox detection with full sandbox response in history."""
        handler = SandboxHandler("https://example.com/auth")

        # Generate a sandbox response
        sandbox_response = await handler.generate_login_banner()

        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": sandbox_response["choices"][0]["message"]["content"],
            },
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is True

    def test_detect_sandbox_history_case_insensitive(self) -> None:
        """Test that sandbox detection is case-sensitive for exact markers."""
        handler = SandboxHandler("https://example.com/auth")

        # Test with exact marker (should detect)
        messages_exact = [
            {
                "role": "assistant",
                "content": "# Authentication Required\nPlease authenticate.",
            }
        ]
        assert handler.detect_sandbox_history(messages_exact) is True

        # Test with different case in header
        messages_different = [
            {
                "role": "assistant",
                "content": "# authentication required\nPlease authenticate.",
            }
        ]
        result = handler.detect_sandbox_history(messages_different)
        # The implementation is case-insensitive, so this should be True
        assert result is True

    def test_detect_sandbox_history_with_none_content(self) -> None:
        """Test sandbox detection handles None content gracefully."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {"role": "user", "content": None},
            {"role": "assistant", "content": "Hello"},
        ]

        # Should not raise exception
        result = handler.detect_sandbox_history(messages)

        assert result is False

    def test_detect_sandbox_history_with_missing_content_key(self) -> None:
        """Test sandbox detection handles missing content key gracefully."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {"role": "user"},
            {"role": "assistant", "content": "Hello"},
        ]

        # Should not raise exception
        result = handler.detect_sandbox_history(messages)

        assert result is False

    def test_detect_sandbox_history_multiple_markers(self) -> None:
        """Test sandbox detection with multiple marker types."""
        handler = SandboxHandler("https://example.com/auth")

        # Test each marker individually
        markers = [
            "# Authentication Required",
            "Authentication Required",
            "Welcome to the LLM Proxy with SSO authentication",
        ]

        for marker in markers:
            messages = [{"role": "assistant", "content": marker}]
            result = handler.detect_sandbox_history(messages)
            assert (
                result is True
            ), f"Should detect sandbox content with marker: {marker}"

    def test_detect_sandbox_history_marker_in_middle_of_content(self) -> None:
        """Test sandbox detection when marker is in middle of content."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {
                "role": "assistant",
                "content": "Some text before\n# Authentication Required\nSome text after",
            }
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is True

    @pytest.mark.asyncio
    async def test_generate_login_banner_response_id(self) -> None:
        """Test that login banner has sandbox ID."""
        handler = SandboxHandler("https://example.com/auth")
        response = await handler.generate_login_banner()

        assert response["id"] == "chatcmpl-sandbox"

    @pytest.mark.asyncio
    async def test_generate_login_banner_response_model(self) -> None:
        """Test that login banner has sandbox model."""
        handler = SandboxHandler("https://example.com/auth")
        response = await handler.generate_login_banner()

        assert response["model"] == "sandbox"

    @pytest.mark.asyncio
    async def test_generate_login_banner_timestamp(self) -> None:
        """Test that login banner has valid timestamp."""
        handler = SandboxHandler("https://example.com/auth")
        response = await handler.generate_login_banner()

        # Verify timestamp is present and positive
        assert "created" in response
        assert isinstance(response["created"], int)
        assert response["created"] > 0

    def test_format_as_completion_response_empty_message(self) -> None:
        """Test formatting empty message as completion response."""
        handler = SandboxHandler("https://example.com/auth")
        response = handler.format_as_completion_response("")

        # Should still have valid structure
        assert response["choices"][0]["message"]["content"] == ""
        assert response["object"] == "chat.completion"

    def test_format_as_completion_response_multiline_message(self) -> None:
        """Test formatting multiline message as completion response."""
        handler = SandboxHandler("https://example.com/auth")
        message = "Line 1\nLine 2\nLine 3"

        response = handler.format_as_completion_response(message)

        assert response["choices"][0]["message"]["content"] == message

    def test_format_as_completion_response_special_characters(self) -> None:
        """Test formatting message with special characters."""
        handler = SandboxHandler("https://example.com/auth")
        message = "Special chars: \n\t\r\"'\\/"

        response = handler.format_as_completion_response(message)

        assert response["choices"][0]["message"]["content"] == message

    def test_detect_sandbox_history_with_mixed_content(self) -> None:
        """Test sandbox detection with mix of sandbox and regular content."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {
                "role": "assistant",
                "content": "# Authentication Required\nPlease authenticate.",
            },
            {"role": "user", "content": "Another message"},
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is True

    def test_detect_sandbox_history_sandbox_at_beginning(self) -> None:
        """Test sandbox detection when sandbox content is at beginning."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {
                "role": "assistant",
                "content": "# Authentication Required\nPlease authenticate.",
            },
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is True

    def test_detect_sandbox_history_sandbox_at_end(self) -> None:
        """Test sandbox detection when sandbox content is at end."""
        handler = SandboxHandler("https://example.com/auth")

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {
                "role": "assistant",
                "content": "# Authentication Required\nPlease authenticate.",
            },
        ]

        result = handler.detect_sandbox_history(messages)

        assert result is True

    @pytest.mark.asyncio
    async def test_generate_login_banner_generates_token(self) -> None:
        """Test that generate_login_banner generates and appends token when repository provided."""
        mock_repo = MagicMock()
        mock_repo.create_login_token = AsyncMock(return_value="test-token-123")

        handler = SandboxHandler("https://example.com/auth", token_repository=mock_repo)

        response = await handler.generate_login_banner()
        message_content = response["choices"][0]["message"]["content"]

        assert "https://example.com/auth?token=test-token-123" in message_content
        mock_repo.create_login_token.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_login_banner_handles_token_error(self) -> None:
        """Test that generate_login_banner handles token generation failure gracefully."""
        mock_repo = MagicMock()
        mock_repo.create_login_token = AsyncMock(side_effect=Exception("DB Error"))

        handler = SandboxHandler("https://example.com/auth", token_repository=mock_repo)

        response = await handler.generate_login_banner()
        message_content = response["choices"][0]["message"]["content"]

        # Should fallback to URL without token
        assert "https://example.com/auth" in message_content
        assert "token=" not in message_content
