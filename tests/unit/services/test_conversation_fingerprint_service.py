"""Unit tests for ConversationFingerprintService."""

from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprint,
    ConversationFingerprintService,
)


class TestConversationFingerprintService:
    """Tests for conversation fingerprint computation."""

    @pytest.fixture
    def service(self) -> ConversationFingerprintService:
        """Create a fingerprint service instance."""
        return ConversationFingerprintService()

    @pytest.fixture
    def sample_messages(self) -> list[ChatMessage]:
        """Create sample messages for testing."""
        return [
            ChatMessage(role="user", content="Hello, how are you?"),
            ChatMessage(role="assistant", content="I'm doing well, thank you!"),
            ChatMessage(role="user", content="Can you help me with a task?"),
            ChatMessage(role="assistant", content="Of course! What do you need?"),
            ChatMessage(role="user", content="I need to implement a feature."),
        ]

    def test_compute_fingerprint_basic(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test basic fingerprint computation."""
        result = service.compute_fingerprint(sample_messages)

        assert isinstance(result, ConversationFingerprint)
        assert len(result.fingerprint) == 32  # Truncated SHA256 hex digest
        assert result.message_count == 5
        assert result.last_role == "user"

    def test_compute_fingerprint_empty_messages(
        self, service: ConversationFingerprintService
    ) -> None:
        """Test fingerprint computation with empty message list."""
        result = service.compute_fingerprint([])

        assert isinstance(result, ConversationFingerprint)
        assert result.fingerprint == "empty"  # Special value for empty list
        assert result.message_count == 0
        assert result.last_role is None

    def test_compute_fingerprint_stability(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test that same messages produce same fingerprint."""
        result1 = service.compute_fingerprint(sample_messages)
        result2 = service.compute_fingerprint(sample_messages)

        assert result1.fingerprint == result2.fingerprint
        assert result1.message_count == result2.message_count
        assert result1.last_role == result2.last_role

    def test_compute_fingerprint_different_content(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test that different content produces different fingerprint."""
        modified_messages = sample_messages.copy()
        modified_messages[-1] = ChatMessage(
            role="user", content="Different content here"
        )

        result1 = service.compute_fingerprint(sample_messages)
        result2 = service.compute_fingerprint(modified_messages)

        assert result1.fingerprint != result2.fingerprint

    def test_compute_fingerprint_different_order(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test that different order produces different fingerprint."""
        reversed_messages = list(reversed(sample_messages))

        result1 = service.compute_fingerprint(sample_messages)
        result2 = service.compute_fingerprint(reversed_messages)

        assert result1.fingerprint != result2.fingerprint

    def test_compute_fingerprint_subset(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test that subset produces different fingerprint."""
        subset_messages = sample_messages[:3]

        result1 = service.compute_fingerprint(sample_messages)
        result2 = service.compute_fingerprint(subset_messages)

        assert result1.fingerprint != result2.fingerprint
        assert result1.message_count > result2.message_count

    def test_compute_fingerprint_with_limit(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test fingerprint computation with message limit."""
        # Create a service with limit of 3 messages
        limited_service = ConversationFingerprintService(fingerprint_message_count=3)

        result = limited_service.compute_fingerprint(sample_messages)

        # Should only consider last 3 messages
        assert result.message_count == 3
        assert result.last_role == "user"

        # Verify it matches computing fingerprint on subset
        last_three = sample_messages[-3:]
        result_subset = service.compute_fingerprint(last_three)
        assert result.fingerprint == result_subset.fingerprint

    def test_compute_rolling_fingerprints(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test rolling fingerprint computation."""
        window_size = 3
        rolling_fps = service.compute_rolling_fingerprints(sample_messages, window_size)

        # Should have len(messages) - window_size + 1 fingerprints
        expected_count = len(sample_messages) - window_size + 1
        assert len(rolling_fps) == expected_count

        # Each fingerprint should be unique (assuming varied content)
        assert len(set(rolling_fps)) == expected_count

    def test_compute_rolling_fingerprints_small_window(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test rolling fingerprints with window size of 1."""
        rolling_fps = service.compute_rolling_fingerprints(
            sample_messages, window_size=1
        )

        # Should have one fingerprint per message
        assert len(rolling_fps) == len(sample_messages)

    def test_compute_rolling_fingerprints_large_window(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test rolling fingerprints with window larger than message count."""
        window_size = len(sample_messages) + 5
        rolling_fps = service.compute_rolling_fingerprints(sample_messages, window_size)

        # Should return empty list (window too large)
        assert len(rolling_fps) == 0

    def test_compute_rolling_fingerprints_empty(
        self, service: ConversationFingerprintService
    ) -> None:
        """Test rolling fingerprints with empty message list."""
        rolling_fps = service.compute_rolling_fingerprints([], window_size=3)

        # Should return empty list
        assert rolling_fps == []

    def test_fingerprint_ignores_metadata(
        self, service: ConversationFingerprintService
    ) -> None:
        """Test that fingerprint ignores metadata like tool_call_id."""
        messages1 = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(
                role="assistant",
                content="Hi",
                tool_calls=[
                    ToolCall(
                        id="call_123",
                        type="function",
                        function=FunctionCall(name="test", arguments="{}"),
                    )
                ],
            ),
        ]

        messages2 = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(
                role="assistant",
                content="Hi",
                tool_calls=[
                    ToolCall(
                        id="call_456",
                        type="function",
                        function=FunctionCall(name="test", arguments="{}"),
                    )
                ],
            ),
        ]

        result1 = service.compute_fingerprint(messages1)
        result2 = service.compute_fingerprint(messages2)

        # Should produce same fingerprint since content and roles are same
        assert result1.fingerprint == result2.fingerprint

    def test_fingerprint_with_tool_results(
        self, service: ConversationFingerprintService
    ) -> None:
        """Test fingerprint computation with tool results."""
        messages = [
            ChatMessage(role="user", content="Run a command"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        function=FunctionCall(name="run_cmd", arguments="{}"),
                    )
                ],
            ),
            ChatMessage(role="tool", content="Command executed", tool_call_id="call_1"),
            ChatMessage(role="assistant", content="Done!"),
        ]

        result = service.compute_fingerprint(messages)

        assert result.message_count == 4
        assert result.last_role == "assistant"
        assert len(result.fingerprint) == 32

    def test_fingerprint_with_system_messages(
        self, service: ConversationFingerprintService
    ) -> None:
        """Test fingerprint computation with system messages."""
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant"),
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ]

        result = service.compute_fingerprint(messages)

        assert result.message_count == 3
        assert result.last_role == "assistant"
        assert len(result.fingerprint) == 32

    def test_fingerprint_conversation_growth(
        self, service: ConversationFingerprintService
    ) -> None:
        """Test that growing conversation produces different fingerprints."""
        messages_base = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi"),
        ]

        messages_extended = [
            *messages_base,
            ChatMessage(role="user", content="How are you?"),
        ]

        fp_base = service.compute_fingerprint(messages_base)
        fp_extended = service.compute_fingerprint(messages_extended)

        assert fp_base.fingerprint != fp_extended.fingerprint
        assert fp_base.message_count < fp_extended.message_count

    def test_compute_rolling_fingerprints_consistency(
        self,
        service: ConversationFingerprintService,
        sample_messages: list[ChatMessage],
    ) -> None:
        """Test that rolling fingerprints are consistent with manual computation."""
        window_size = 3
        rolling_fps = service.compute_rolling_fingerprints(sample_messages, window_size)

        # Manually compute first window fingerprint
        first_window = sample_messages[:window_size]
        manual_fp = service.compute_fingerprint(first_window)

        assert rolling_fps[0] == manual_fp.fingerprint

        # Manually compute last window fingerprint
        last_window = sample_messages[-window_size:]
        manual_fp_last = service.compute_fingerprint(last_window)

        assert rolling_fps[-1] == manual_fp_last.fingerprint
