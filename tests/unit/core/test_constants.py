"""Test file to verify constants are accessible and correctly imported."""

import pytest
from src.core.constants import (
    BACKEND_ANTHROPIC,
    BACKEND_GEMINI,
    # Backend constants
    BACKEND_OPENAI,
    # Command output constants
    BACKEND_SET_MESSAGE,
    CONTENT_TYPE_EVENT_STREAM,
    # API response constants
    CONTENT_TYPE_JSON,
    FIELD_CONTENT,
    FIELD_ID,
    FIELD_MODEL,
    FIELD_OBJECT,
    MODEL_CLAUDE_3_SONNET,
    MODEL_GPT_4,
    # Model constants
    MODEL_GPT_35_TURBO,
    MODEL_SET_MESSAGE,
    OBJECT_TYPE_CHAT_COMPLETION,
    OBJECT_TYPE_LIST,
    ROLE_ASSISTANT,
    ROLE_USER,
)


def test_api_response_constants():
    """Test that API response constants have expected values."""
    assert CONTENT_TYPE_JSON == "application/json"
    assert CONTENT_TYPE_EVENT_STREAM == "text/event-stream"
    assert OBJECT_TYPE_LIST == "list"
    assert OBJECT_TYPE_CHAT_COMPLETION == "chat.completion"
    assert FIELD_OBJECT == "object"
    assert FIELD_ID == "id"
    assert FIELD_MODEL == "model"
    assert FIELD_CONTENT == "content"
    assert ROLE_USER == "user"
    assert ROLE_ASSISTANT == "assistant"


def test_backend_constants():
    """Test that backend constants have expected values."""
    assert BACKEND_OPENAI == "openai"
    assert BACKEND_ANTHROPIC == "anthropic"
    assert BACKEND_GEMINI == "gemini"


def test_model_constants():
    """Test that model constants have expected values."""
    assert MODEL_GPT_35_TURBO == "gpt-3.5-turbo"
    assert MODEL_GPT_4 == "gpt-4"
    assert MODEL_CLAUDE_3_SONNET == "claude-3-sonnet-20240229"


def test_command_output_constants():
    """Test that command output constants have expected format."""
    assert BACKEND_SET_MESSAGE == "Backend set to {backend}"
    assert MODEL_SET_MESSAGE == "Model set to {model}"

    # Test formatting
    formatted_backend = BACKEND_SET_MESSAGE.format(backend="openai")
    assert formatted_backend == "Backend set to openai"

    formatted_model = MODEL_SET_MESSAGE.format(model="gpt-4")
    assert formatted_model == "Model set to gpt-4"


if __name__ == "__main__":
    pytest.main([__file__])
