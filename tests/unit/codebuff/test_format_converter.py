"""
Unit tests for Codebuff FormatConverter.

Tests format conversion between Codebuff and OpenAI formats,
and creation of various response messages.
"""

from __future__ import annotations

import pytest

from src.codebuff.format_converter import FormatConverter


class TestCodebuffToOpenAI:
    """Tests for codebuff_to_openai conversion."""

    def test_converts_role_content_format(self):
        """Test conversion of messages already in OpenAI format."""
        converter = FormatConverter()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        session_state = {}

        result = converter.codebuff_to_openai(messages, session_state)

        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there"}

    def test_converts_text_format(self):
        """Test conversion of messages with text field."""
        converter = FormatConverter()
        messages = [{"text": "Hello world"}]
        session_state = {}

        result = converter.codebuff_to_openai(messages, session_state)

        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello world"}

    def test_converts_nested_message_format(self):
        """Test conversion of messages with nested message field."""
        converter = FormatConverter()
        messages = [
            {"message": {"role": "user", "content": "Hello"}},
            {"message": {"role": "assistant", "content": "Hi"}},
        ]
        session_state = {}

        result = converter.codebuff_to_openai(messages, session_state)

        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi"}

    def test_converts_type_format(self):
        """Test conversion of messages with type field."""
        converter = FormatConverter()
        messages = [
            {"type": "user", "content": "Hello"},
            {"type": "assistant", "content": "Hi"},
            {"type": "system", "content": "System message"},
        ]
        session_state = {}

        result = converter.codebuff_to_openai(messages, session_state)

        assert len(result) == 3
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi"}
        assert result[2] == {"role": "system", "content": "System message"}

    def test_handles_empty_messages(self):
        """Test conversion of empty message list."""
        converter = FormatConverter()
        messages = []
        session_state = {}

        result = converter.codebuff_to_openai(messages, session_state)

        assert result == []

    def test_handles_mixed_formats(self):
        """Test conversion of messages in different formats."""
        converter = FormatConverter()
        messages = [
            {"role": "user", "content": "First"},
            {"text": "Second"},
            {"type": "assistant", "content": "Third"},
            {"message": {"role": "user", "content": "Fourth"}},
        ]
        session_state = {}

        result = converter.codebuff_to_openai(messages, session_state)

        assert len(result) == 4
        assert result[0] == {"role": "user", "content": "First"}
        assert result[1] == {"role": "user", "content": "Second"}
        assert result[2] == {"role": "assistant", "content": "Third"}
        assert result[3] == {"role": "user", "content": "Fourth"}


class TestCreateResponseChunk:
    """Tests for create_response_chunk."""

    def test_creates_valid_chunk_message(self):
        """Test creation of response chunk message."""
        converter = FormatConverter()

        result = converter.create_response_chunk("prompt-123", "Hello world")

        assert result["type"] == "action"
        assert result["data"]["type"] == "response-chunk"
        assert result["data"]["userInputId"] == "prompt-123"
        assert result["data"]["chunk"] == "Hello world"

    def test_handles_empty_chunk(self):
        """Test creation of chunk with empty text."""
        converter = FormatConverter()

        result = converter.create_response_chunk("prompt-123", "")

        assert result["type"] == "action"
        assert result["data"]["type"] == "response-chunk"
        assert result["data"]["userInputId"] == "prompt-123"
        assert result["data"]["chunk"] == ""

    def test_handles_multiline_chunk(self):
        """Test creation of chunk with multiline text."""
        converter = FormatConverter()
        text = "Line 1\nLine 2\nLine 3"

        result = converter.create_response_chunk("prompt-123", text)

        assert result["data"]["chunk"] == text


class TestCreatePromptResponse:
    """Tests for create_prompt_response."""

    def test_creates_valid_prompt_response(self):
        """Test creation of prompt response message."""
        converter = FormatConverter()
        session_state = {"conversation_history": []}

        result = converter.create_prompt_response("prompt-123", session_state)

        assert result["type"] == "action"
        assert result["data"]["type"] == "prompt-response"
        assert result["data"]["promptId"] == "prompt-123"
        assert result["data"]["sessionState"] == session_state
        assert result["data"]["toolCalls"] is None
        assert result["data"]["toolResults"] is None
        assert result["data"]["output"] is None

    def test_includes_session_state(self):
        """Test that session state is included in response."""
        converter = FormatConverter()
        session_state = {
            "conversation_history": [{"role": "user", "content": "Hello"}],
            "context": "some context",
        }

        result = converter.create_prompt_response("prompt-123", session_state)

        assert result["data"]["sessionState"] == session_state


class TestCreateErrorResponse:
    """Tests for create_error_response."""

    def test_creates_valid_error_response(self):
        """Test creation of error response message."""
        converter = FormatConverter()

        result = converter.create_error_response("prompt-123", "Something went wrong")

        assert result["type"] == "action"
        assert result["data"]["type"] == "prompt-error"
        assert result["data"]["userInputId"] == "prompt-123"
        assert result["data"]["message"] == "Something went wrong"
        assert result["data"]["error"] == "Something went wrong"
        assert result["data"]["remainingBalance"] is None

    def test_includes_remaining_balance(self):
        """Test error response with remaining balance."""
        converter = FormatConverter()

        result = converter.create_error_response(
            "prompt-123", "Insufficient credits", remaining_balance=10.5
        )

        assert result["data"]["remainingBalance"] == 10.5


class TestCreateActionErrorResponse:
    """Tests for create_action_error_response."""

    def test_creates_valid_action_error(self):
        """Test creation of action error message."""
        converter = FormatConverter()

        result = converter.create_action_error_response("Invalid action")

        assert result["type"] == "action"
        assert result["data"]["type"] == "action-error"
        assert result["data"]["message"] == "Invalid action"
        assert result["data"]["error"] == "Invalid action"
        assert result["data"]["remainingBalance"] is None


class TestCreateInitResponse:
    """Tests for create_init_response."""

    def test_creates_valid_init_response(self):
        """Test creation of init response message."""
        converter = FormatConverter()

        result = converter.create_init_response()

        assert result["type"] == "action"
        assert result["data"]["type"] == "init-response"
        assert result["data"]["message"] is None
        assert result["data"]["agentNames"] is None
        assert result["data"]["usage"] == 0.0
        assert result["data"]["remainingBalance"] == float("inf")
        assert result["data"]["next_quota_reset"] is None

    def test_includes_optional_fields(self):
        """Test init response with optional fields."""
        converter = FormatConverter()
        agent_names = {"default": "Assistant"}

        result = converter.create_init_response(
            message="Initialized successfully",
            agent_names=agent_names,
            usage=5.0,
            remaining_balance=95.0,
        )

        assert result["data"]["message"] == "Initialized successfully"
        assert result["data"]["agentNames"] == agent_names
        assert result["data"]["usage"] == 5.0
        assert result["data"]["remainingBalance"] == 95.0
