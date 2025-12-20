"""Unit tests for RequestTranslator adapter.

Tests cover wrapping CodexRequestTranslator and implementing IRequestTranslator interface.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    ProcessedMessage,
)
from src.connectors.openai_codex.interfaces import IRequestTranslator
from src.connectors.openai_codex.request_translator import RequestTranslator


class TestRequestTranslator:
    """Test RequestTranslator adapter implementation."""

    @pytest.fixture
    def mock_codex_translator(self):
        """Create a mock CodexRequestTranslator."""
        translator = MagicMock()
        translator.build_input_items.return_value = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "test"}],
            }
        ]
        return translator

    @pytest.fixture
    def translator(self, mock_codex_translator):
        """Create a RequestTranslator instance for testing."""
        return RequestTranslator(mock_codex_translator)

    @pytest.fixture
    def capabilities(self):
        """Create test capabilities."""
        return CodexClientCapabilities()

    def test_translator_implements_interface(self, translator):
        """Verify translator implements IRequestTranslator interface."""
        assert isinstance(translator, IRequestTranslator)

    def test_translate_messages(self, translator, mock_codex_translator, capabilities):
        """Test translating messages to Codex input items."""
        messages = [
            ProcessedMessage(role="user", content="Hello"),
            ProcessedMessage(role="assistant", content="Hi there"),
        ]

        result = translator.translate_messages(messages)

        assert isinstance(result, list)
        # Verify that build_input_items was called
        mock_codex_translator.build_input_items.assert_called_once()
        call_kwargs = mock_codex_translator.build_input_items.call_args[1]
        assert "processed_messages" in call_kwargs

    def test_translate_tool_calls(self, translator, mock_codex_translator):
        """Test translating tool calls to Codex input items."""
        from src.core.domain.chat import ToolCall as DomainToolCall

        tool_calls = [
            DomainToolCall(
                id="call_123",
                type="function",
                function={"name": "test_tool", "arguments": '{"arg": "value"}'},
            )
        ]

        result = translator.translate_tool_calls(tool_calls)

        assert isinstance(result, list)
        # Tool calls should be converted to function_call input items
        assert len(result) > 0
