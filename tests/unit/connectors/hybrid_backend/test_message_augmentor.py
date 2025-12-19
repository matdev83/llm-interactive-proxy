"""Unit tests for MessageAugmentor service.

Tests cover injecting reasoning into message lists using various strategies.

Requirements satisfied:
- Req 2.3: MessageAugmentor extraction
- Req 11: Test-preserving migration
"""

from unittest.mock import Mock, patch

import pytest
from src.connectors.hybrid_backend.protocols import (
    IMessageAugmentor,
    IReasoningMarkupProcessor,
)
from src.core.config.app_config import AppConfig, BackendSettings


class TestMessageAugmentor:
    """Test MessageAugmentor service implementation."""

    @pytest.fixture
    def mock_markup_processor(self):
        """Create a mock ReasoningMarkupProcessor."""
        mock = Mock(spec=IReasoningMarkupProcessor)
        mock.format_for_model.return_value = "<thinking>Reasoning content</thinking>"
        return mock

    @pytest.fixture
    def app_config(self):
        """Create AppConfig for testing."""
        config = AppConfig().model_copy(
            update={"backends": BackendSettings(hybrid_backend_repeat_messages=False)}
        )
        return config

    @pytest.fixture
    def augmentor(self, mock_markup_processor, app_config):
        """Create a MessageAugmentor instance for testing."""
        from src.connectors.hybrid_backend.services.message_augmentor import (
            MessageAugmentor,
        )

        return MessageAugmentor(
            markup_processor=mock_markup_processor, config=app_config
        )

    def test_augmentor_implements_protocol(self, augmentor):
        """Verify augmentor implements IMessageAugmentor protocol."""
        assert isinstance(augmentor, IMessageAugmentor)

    def test_augment_system_message_injection(self, augmentor, mock_markup_processor):
        """Test augment() injects reasoning as system message when backend supports it."""
        messages = [{"role": "user", "content": "Hello"}]
        reasoning_output = "Some reasoning"

        with patch(
            "src.connectors.hybrid_backend.services.message_augmentor.supports_system_messages",
            return_value=True,
        ):
            result = augmentor.augment(messages, reasoning_output, "openai")

        assert len(result) >= len(messages)
        # Should have system message
        system_msgs = [m for m in result if m.get("role") == "system"]
        assert len(system_msgs) > 0
        assert "Consider this reasoning" in system_msgs[0]["content"]
        mock_markup_processor.format_for_model.assert_called_once()

    def test_augment_user_message_prepending(self, augmentor, mock_markup_processor):
        """Test augment() prepends reasoning to user message when backend doesn't support system."""
        messages = [{"role": "user", "content": "Hello"}]
        reasoning_output = "Some reasoning"

        with patch(
            "src.connectors.hybrid_backend.services.message_augmentor.supports_system_messages",
            return_value=False,
        ):
            result = augmentor.augment(messages, reasoning_output, "gemini")

        assert len(result) == len(messages)
        assert result[0]["role"] == "user"
        assert "<thinking>" in result[0]["content"]
        assert "Hello" in result[0]["content"]
        mock_markup_processor.format_for_model.assert_called_once()

    def test_augment_repeat_messages_mode(self, augmentor, mock_markup_processor):
        """Test augment() appends assistant message in repeat-messages mode."""
        from src.connectors.hybrid_backend.services.message_augmentor import (
            MessageAugmentor,
        )

        app_config = AppConfig().model_copy(
            update={"backends": BackendSettings(hybrid_backend_repeat_messages=True)}
        )
        augmentor = MessageAugmentor(
            markup_processor=mock_markup_processor, config=app_config
        )
        messages = [{"role": "user", "content": "Hello"}]
        reasoning_output = "Some reasoning"

        with patch(
            "src.connectors.hybrid_backend.services.message_augmentor.supports_system_messages",
            return_value=True,
        ):
            result = augmentor.augment(messages, reasoning_output, "openai")

        # Should have original messages plus assistant message with reasoning
        assert len(result) > len(messages)
        assistant_msgs = [m for m in result if m.get("role") == "assistant"]
        assert len(assistant_msgs) > 0
        assert assistant_msgs[-1].get("reasoning") is not None

    def test_augment_empty_messages(self, augmentor):
        """Test augment() handles empty message list."""
        result = augmentor.augment([], "reasoning", "openai")

        assert result == []

    def test_augment_existing_system_message(self, augmentor, mock_markup_processor):
        """Test augment() augments existing system message."""
        messages = [
            {"role": "system", "content": "Existing system content"},
            {"role": "user", "content": "Hello"},
        ]
        reasoning_output = "Some reasoning"

        with patch(
            "src.connectors.hybrid_backend.services.message_augmentor.supports_system_messages",
            return_value=True,
        ):
            result = augmentor.augment(messages, reasoning_output, "openai")

        # Should augment existing system message, not create new one
        system_msgs = [m for m in result if m.get("role") == "system"]
        assert len(system_msgs) == 1
        assert "Existing system content" in system_msgs[0]["content"]
        assert "Consider this reasoning" in system_msgs[0]["content"]

    def test_augment_no_reasoning_content(self, augmentor, mock_markup_processor):
        """Test augment() returns original messages if no reasoning content."""
        mock_markup_processor.format_for_model.return_value = ""
        messages = [{"role": "user", "content": "Hello"}]

        result = augmentor.augment(messages, "", "openai")

        assert result == messages

    def test_augment_preserves_message_structure(
        self, augmentor, mock_markup_processor
    ):
        """Test augment() preserves original message structure."""
        messages = [
            {"role": "user", "content": "Hello", "name": "user1"},
            {"role": "assistant", "content": "Hi there"},
        ]

        with patch(
            "src.connectors.hybrid_backend.services.message_augmentor.supports_system_messages",
            return_value=False,
        ):
            result = augmentor.augment(messages, "reasoning", "gemini")

        # Original messages should be preserved
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "Hi there"
        # First message should have reasoning prepended
        assert result[0]["name"] == "user1"
