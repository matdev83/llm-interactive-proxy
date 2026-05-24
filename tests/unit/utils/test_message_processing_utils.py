from __future__ import annotations

from src.core.utils.message_processing_utils import (
    find_last_assistant_message,
    is_message_processed,
    mark_message_processed,
)


class MessageObject:
    """Mock message object for testing object-based messages."""

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


class TestIsMessageProcessed:
    """Tests for is_message_processed function."""

    def test_dict_message_not_processed_by_default(self) -> None:
        """Test that dict messages are not marked as processed by default."""
        message = {"role": "assistant", "content": "Hello"}
        assert is_message_processed(message) is False

    def test_object_message_not_processed_by_default(self) -> None:
        """Test that object messages are not marked as processed by default."""
        message = MessageObject("assistant", "Hello")
        assert is_message_processed(message) is False

    def test_dict_message_with_marker_is_processed(self) -> None:
        """Test that dict messages with marker are detected as processed."""
        message = {
            "role": "assistant",
            "content": "Hello",
            "_tool_calls_processed": True,
        }
        assert is_message_processed(message) is True

    def test_object_message_with_marker_is_processed(self) -> None:
        """Test that object messages with marker are detected as processed."""
        message = MessageObject("assistant", "Hello")
        message._tool_calls_processed = True  # type: ignore
        assert is_message_processed(message) is True

    def test_dict_message_with_false_marker(self) -> None:
        """Test that dict messages with False marker are not processed."""
        message = {
            "role": "assistant",
            "content": "Hello",
            "_tool_calls_processed": False,
        }
        assert is_message_processed(message) is False

    def test_object_message_with_false_marker(self) -> None:
        """Test that object messages with False marker are not processed."""
        message = MessageObject("assistant", "Hello")
        message._tool_calls_processed = False  # type: ignore
        assert is_message_processed(message) is False


class TestMarkMessageProcessed:
    """Tests for mark_message_processed function."""

    def test_mark_dict_message_as_processed(self) -> None:
        """Test marking a dict message as processed."""
        message = {"role": "assistant", "content": "Hello"}
        mark_message_processed(message)
        assert message["_tool_calls_processed"] is True

    def test_mark_object_message_as_processed(self) -> None:
        """Test marking an object message as processed."""
        message = MessageObject("assistant", "Hello")
        mark_message_processed(message)
        assert message._tool_calls_processed is True  # type: ignore

    def test_mark_does_not_modify_core_structure_dict(self) -> None:
        """Test that marking doesn't modify core message structure for dict."""
        message = {"role": "assistant", "content": "Hello", "tool_calls": []}
        original_keys = set(message.keys())
        mark_message_processed(message)

        # Check that only the marker was added
        assert set(message.keys()) == original_keys | {"_tool_calls_processed"}
        assert message["role"] == "assistant"
        assert message["content"] == "Hello"
        assert message["tool_calls"] == []

    def test_mark_does_not_modify_core_structure_object(self) -> None:
        """Test that marking doesn't modify core message structure for object."""
        message = MessageObject("assistant", "Hello")
        mark_message_processed(message)

        # Check that core attributes are unchanged
        assert message.role == "assistant"
        assert message.content == "Hello"
        assert hasattr(message, "_tool_calls_processed")

    def test_mark_is_idempotent_dict(self) -> None:
        """Test that marking multiple times is safe for dict messages."""
        message = {"role": "assistant", "content": "Hello"}
        mark_message_processed(message)
        mark_message_processed(message)
        mark_message_processed(message)
        assert message["_tool_calls_processed"] is True

    def test_mark_is_idempotent_object(self) -> None:
        """Test that marking multiple times is safe for object messages."""
        message = MessageObject("assistant", "Hello")
        mark_message_processed(message)
        mark_message_processed(message)
        mark_message_processed(message)
        assert message._tool_calls_processed is True  # type: ignore


class TestFindLastAssistantMessage:
    """Tests for find_last_assistant_message function."""

    def test_empty_list_returns_none(self) -> None:
        """Test that empty message list returns None."""
        assert find_last_assistant_message([]) is None

    def test_no_assistant_messages_returns_none(self) -> None:
        """Test that list with no assistant messages returns None."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "How are you?"},
        ]
        assert find_last_assistant_message(messages) is None

    def test_single_assistant_message_dict(self) -> None:
        """Test finding single assistant message in dict format."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        assert find_last_assistant_message(messages) == 1

    def test_single_assistant_message_object(self) -> None:
        """Test finding single assistant message in object format."""
        messages = [
            MessageObject("user", "Hello"),
            MessageObject("assistant", "Hi there"),
        ]
        assert find_last_assistant_message(messages) == 1

    def test_multiple_assistant_messages_returns_last(self) -> None:
        """Test that function returns the last assistant message index."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm good"},
            {"role": "user", "content": "Great!"},
        ]
        assert find_last_assistant_message(messages) == 3

    def test_last_message_is_assistant(self) -> None:
        """Test when the last message is an assistant message."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm good"},
        ]
        assert find_last_assistant_message(messages) == 3

    def test_mixed_dict_and_object_messages(self) -> None:
        """Test with mixed dict and object message formats."""
        messages = [
            {"role": "user", "content": "Hello"},
            MessageObject("assistant", "Hi there"),
            {"role": "user", "content": "How are you?"},
            MessageObject("assistant", "I'm good"),
        ]
        assert find_last_assistant_message(messages) == 3

    def test_only_assistant_messages(self) -> None:
        """Test list with only assistant messages."""
        messages = [
            {"role": "assistant", "content": "First"},
            {"role": "assistant", "content": "Second"},
            {"role": "assistant", "content": "Third"},
        ]
        assert find_last_assistant_message(messages) == 2

    def test_assistant_message_at_start(self) -> None:
        """Test when assistant message is only at the start."""
        messages = [
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]
        assert find_last_assistant_message(messages) == 0


class TestIntegration:
    """Integration tests for message processing workflow."""

    def test_full_workflow_dict_messages(self) -> None:
        """Test complete workflow with dict messages."""
        message = {"role": "assistant", "content": "Hello"}

        # Initially not processed
        assert is_message_processed(message) is False

        # Mark as processed
        mark_message_processed(message)

        # Now it's processed
        assert is_message_processed(message) is True

    def test_full_workflow_object_messages(self) -> None:
        """Test complete workflow with object messages."""
        message = MessageObject("assistant", "Hello")

        # Initially not processed
        assert is_message_processed(message) is False

        # Mark as processed
        mark_message_processed(message)

        # Now it's processed
        assert is_message_processed(message) is True

    def test_processing_only_last_assistant_message(self) -> None:
        """Test typical use case: process only last assistant message."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm good"},
        ]

        # Mark historical messages as processed
        for i in range(len(messages) - 1):
            if messages[i].get("role") == "assistant":
                mark_message_processed(messages[i])

        # Find last assistant message
        last_idx = find_last_assistant_message(messages)
        assert last_idx == 3

        # Check processing status
        assert is_message_processed(messages[1]) is True  # Historical
        assert is_message_processed(messages[3]) is False  # New

        # Process the last message
        mark_message_processed(messages[last_idx])
        assert is_message_processed(messages[3]) is True
