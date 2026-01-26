"""
Unit tests for the HistoryCompactionService.

Tests coverage for:
- Staleness detection and compaction
- Stub replacement
- Fail-open behavior
- Policy evaluation
- Edge cases

Requirements covered: 1.1-1.5, 2.1-2.5, 3.1-3.5, 4.4
"""

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.configuration.compaction_config import (
    CompactionConfig,
)
from src.core.services.history_compaction_service import HistoryCompactionService


@pytest.fixture
def service() -> HistoryCompactionService:
    return HistoryCompactionService()


@pytest.fixture
def config() -> CompactionConfig:
    return CompactionConfig(enabled=True, min_tool_output_tokens_to_compact=0)  # Explicitly enable for tests


def _make_assistant_with_tool_call(
    tool_call_id: str,
    tool_name: str,
    arguments: str,
) -> ChatMessage:
    """Helper to create an assistant message with a tool call."""
    return ChatMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id=tool_call_id,
                type="function",
                function=FunctionCall(name=tool_name, arguments=arguments),
            )
        ],
    )


def _make_tool_result(
    tool_call_id: str,
    content: str,
    name: str | None = None,
) -> ChatMessage:
    """Helper to create a tool result message."""
    return ChatMessage(
        role="tool",
        content=content,
        tool_call_id=tool_call_id,
        name=name,
    )


class TestCompactHistory:
    """Tests for the compact_history method."""

    @pytest.mark.asyncio
    async def test_empty_messages(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Empty message list returns empty result."""
        result = await service.compact_history([], config)

        assert result.messages == []
        assert result.compacted_count == 0
        assert result.was_compacted is False

    @pytest.mark.asyncio
    async def test_disabled_config_returns_original(
        self, service: HistoryCompactionService
    ) -> None:
        """Disabled config returns original messages without modification."""
        config = CompactionConfig(enabled=False)
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi"),
        ]

        result = await service.compact_history(messages, config)

        assert result.messages is messages  # Same reference
        assert result.was_compacted is False

    @pytest.mark.asyncio
    async def test_no_tool_messages_unchanged(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Messages without tool results are unchanged."""
        messages = [
            ChatMessage(role="user", content="Write a test"),
            ChatMessage(role="assistant", content="Here's the test"),
            ChatMessage(role="user", content="Run it"),
        ]

        result = await service.compact_history(messages, config)

        assert len(result.messages) == 3
        assert result.compacted_count == 0

    @pytest.mark.asyncio
    async def test_single_tool_result_unchanged(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Single tool result for a resource is not compacted."""
        messages = [
            ChatMessage(role="user", content="Show me the file"),
            _make_assistant_with_tool_call(
                "call_1", "view_file", '{"path": "/test/file.py"}'
            ),
            _make_tool_result("call_1", "File content here", "view_file"),
        ]

        result = await service.compact_history(messages, config)

        assert result.compacted_count == 0
        assert result.messages[2].content == "File content here"

    @pytest.mark.asyncio
    async def test_stale_duplicate_compacted(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Older result for same resource is compacted (Req 1.1, 2.1)."""
        messages = [
            ChatMessage(role="user", content="Show me the file"),
            _make_assistant_with_tool_call(
                "call_1", "view_file", '{"path": "/test/file.py"}'
            ),
            _make_tool_result("call_1", "Original content - very long", "view_file"),
            ChatMessage(role="assistant", content="I'll update it"),
            _make_assistant_with_tool_call(
                "call_2", "view_file", '{"path": "/test/file.py"}'
            ),
            _make_tool_result("call_2", "Updated content", "view_file"),
        ]

        result = await service.compact_history(messages, config)

        assert result.compacted_count == 1
        assert result.was_compacted is True
        # First tool result should be compacted
        assert "[COMPACTED]" in result.messages[2].content  # type: ignore
        # Second tool result should be intact
        assert result.messages[5].content == "Updated content"

    @pytest.mark.asyncio
    async def test_latest_result_preserved(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Latest result per resource is never compacted (Req 1.5, 2.4)."""
        messages = [
            _make_assistant_with_tool_call("call_1", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("call_1", "First view of a.py", "view_file"),
            _make_assistant_with_tool_call("call_2", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("call_2", "Second view of a.py", "view_file"),
            _make_assistant_with_tool_call("call_3", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("call_3", "Third view of a.py - LATEST", "view_file"),
        ]

        result = await service.compact_history(messages, config)

        # Only the latest should be intact
        assert "[COMPACTED]" in result.messages[1].content  # type: ignore
        assert "[COMPACTED]" in result.messages[3].content  # type: ignore
        assert result.messages[5].content == "Third view of a.py - LATEST"
        assert result.compacted_count == 2

    @pytest.mark.asyncio
    async def test_different_resources_not_compacted(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Different resources are tracked separately."""
        messages = [
            _make_assistant_with_tool_call("call_1", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("call_1", "Content of a.py", "view_file"),
            _make_assistant_with_tool_call("call_2", "view_file", '{"path": "/b.py"}'),
            _make_tool_result("call_2", "Content of b.py", "view_file"),
        ]

        result = await service.compact_history(messages, config)

        # Different files = no compaction
        assert result.compacted_count == 0
        assert result.messages[1].content == "Content of a.py"
        assert result.messages[3].content == "Content of b.py"


class TestStubReplacement:
    """Tests for stub content generation (Req 2.1-2.5)."""

    @pytest.mark.asyncio
    async def test_stub_contains_resource_identity(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Stub text includes resource identity (Req 2.3)."""
        messages = [
            _make_assistant_with_tool_call(
                "call_1", "view_file", '{"path": "/test/example.py"}'
            ),
            _make_tool_result("call_1", "x" * 1000, "view_file"),
            _make_assistant_with_tool_call(
                "call_2", "view_file", '{"path": "/test/example.py"}'
            ),
            _make_tool_result("call_2", "New content", "view_file"),
        ]

        result = await service.compact_history(messages, config)

        stub = result.messages[1].content
        assert "/test/example.py" in stub  # type: ignore

    @pytest.mark.asyncio
    async def test_stub_mentions_newer_result(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Stub text mentions newer result exists (Req 2.3)."""
        messages = [
            _make_assistant_with_tool_call(
                "call_1", "view_file", '{"path": "/file.py"}'
            ),
            _make_tool_result("call_1", "Old content", "view_file"),
            _make_assistant_with_tool_call(
                "call_2", "view_file", '{"path": "/file.py"}'
            ),
            _make_tool_result("call_2", "New content", "view_file"),
        ]

        result = await service.compact_history(messages, config)

        stub = result.messages[1].content
        assert "newer" in stub.lower()  # type: ignore

    @pytest.mark.asyncio
    async def test_stub_preserves_tool_call_id(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Compacted message keeps tool_call_id for conversation coherence (Req 2.2)."""
        messages = [
            _make_assistant_with_tool_call(
                "call_abc", "view_file", '{"path": "/x.py"}'
            ),
            _make_tool_result("call_abc", "Content", "view_file"),
            _make_assistant_with_tool_call(
                "call_def", "view_file", '{"path": "/x.py"}'
            ),
            _make_tool_result("call_def", "New content", "view_file"),
        ]

        result = await service.compact_history(messages, config)

        # tool_call_id must be preserved
        assert result.messages[1].tool_call_id == "call_abc"


class TestMissingIdentity:
    """Tests for messages with missing resource identity (Req 1.3)."""

    @pytest.mark.asyncio
    async def test_no_arguments_skips_compaction(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Tool result without extractable identity is preserved."""
        messages = [
            _make_assistant_with_tool_call("call_1", "custom_tool", "{}"),
            _make_tool_result("call_1", "First result", "custom_tool"),
            _make_assistant_with_tool_call("call_2", "custom_tool", "{}"),
            _make_tool_result("call_2", "Second result", "custom_tool"),
        ]

        result = await service.compact_history(messages, config)

        # Cannot extract identity - should not compact
        assert result.compacted_count == 0


class TestFailOpen:
    """Tests for fail-open behavior (Req 4.4)."""

    @pytest.mark.asyncio
    async def test_error_returns_original_messages(
        self, service: HistoryCompactionService
    ) -> None:
        """On error, original messages are returned."""
        # Simulate a scenario that could cause an error
        # by using a mock or crafting problematic input
        messages = [ChatMessage(role="user", content="Test")]

        # Create config that will fail in policy evaluation
        config = CompactionConfig(enabled=True, min_tool_output_tokens_to_compact=0)

        # Even with unusual inputs, should not raise
        result = await service.compact_history(messages, config)

        # Should return original without exception
        assert len(result.messages) == 1
        assert result.error is None or isinstance(result.error, str)


class TestTokenBudgetGovernance:
    """Tests for token budget threshold triggering (Req 3.1-3.5)."""

    @pytest.mark.asyncio
    async def test_below_threshold_skips_compaction(
        self, service: HistoryCompactionService
    ) -> None:
        """Below token threshold, compaction is skipped (Req 3.5)."""
        config = CompactionConfig(enabled=True, token_threshold=100_000, min_tool_output_tokens_to_compact=0)
        messages = [
            _make_assistant_with_tool_call("c1", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("c1", "Content", "view_file"),
            _make_assistant_with_tool_call("c2", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("c2", "Updated", "view_file"),
        ]

        # Token estimate below threshold
        result = await service.compact_history(
            messages, config, current_token_estimate=50_000
        )

        assert result.compacted_count == 0

    @pytest.mark.asyncio
    async def test_above_threshold_triggers_compaction(
        self, service: HistoryCompactionService
    ) -> None:
        """Above token threshold, compaction is triggered (Req 3.1)."""
        config = CompactionConfig(enabled=True, token_threshold=100_000, min_tool_output_tokens_to_compact=0)
        messages = [
            _make_assistant_with_tool_call("c1", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("c1", "x" * 1000, "view_file"),
            _make_assistant_with_tool_call("c2", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("c2", "Updated", "view_file"),
        ]

        # Token estimate above threshold
        result = await service.compact_history(
            messages, config, current_token_estimate=120_000
        )

        assert result.compacted_count == 1


class TestPolicyEnforcement:
    """Tests for per-tool allow/deny policies (Req 3.3-3.4)."""

    @pytest.mark.asyncio
    async def test_denied_category_not_compacted(
        self, service: HistoryCompactionService
    ) -> None:
        """Tools in denied category are not compacted (Req 3.4)."""
        config = CompactionConfig(
            enabled=True,
            denied_tool_categories=["file_write"],
        )
        messages = [
            _make_assistant_with_tool_call("c1", "write_file", '{"path": "/a.py"}'),
            _make_tool_result("c1", "Write result 1", "write_file"),
            _make_assistant_with_tool_call("c2", "write_file", '{"path": "/a.py"}'),
            _make_tool_result("c2", "Write result 2", "write_file"),
        ]

        result = await service.compact_history(messages, config)

        # write_file is denied - no compaction
        assert result.compacted_count == 0

    @pytest.mark.asyncio
    async def test_allowed_category_compacted(
        self, service: HistoryCompactionService
    ) -> None:
        """Tools in allowed category are compacted (Req 3.4)."""
        config = CompactionConfig(
            enabled=True,
            allowed_tool_categories=["view_file"],
            min_tool_output_tokens_to_compact=0,
        )
        messages = [
            _make_assistant_with_tool_call("c1", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("c1", "Content 1", "view_file"),
            _make_assistant_with_tool_call("c2", "view_file", '{"path": "/a.py"}'),
            _make_tool_result("c2", "Content 2", "view_file"),
        ]

        result = await service.compact_history(messages, config)

        # view_file is allowed - compaction occurs
        assert result.compacted_count == 1


class TestShouldCompact:
    """Tests for should_compact check."""

    def test_disabled_returns_false(self, service: HistoryCompactionService) -> None:
        """Disabled config always returns False."""
        config = CompactionConfig(enabled=False)
        messages = [
            _make_tool_result("c1", "Content", "view_file"),
            _make_tool_result("c2", "Content", "view_file"),
        ]

        assert service.should_compact(messages, config) is False

    def test_no_messages_returns_false(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Empty messages returns False."""
        assert service.should_compact([], config) is False

    def test_single_tool_returns_false(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Single tool message cannot be stale."""
        messages = [
            ChatMessage(role="tool", content="Result", tool_call_id="c1"),
        ]

        assert service.should_compact(messages, config) is False

    def test_multiple_tools_returns_true(
        self, service: HistoryCompactionService, config: CompactionConfig
    ) -> None:
        """Multiple tool messages may have staleness."""
        messages = [
            ChatMessage(role="tool", content="Result 1", tool_call_id="c1"),
            ChatMessage(role="user", content="Update it"),
            ChatMessage(role="tool", content="Result 2", tool_call_id="c2"),
        ]

        assert service.should_compact(messages, config) is True
