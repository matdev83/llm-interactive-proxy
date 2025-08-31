"""
Unit tests for Apply Diff Tool Call Handler.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_handlers.apply_diff_handler import ApplyDiffHandler
from src.core.services.tool_call_reactor_service import InMemoryToolCallHistoryTracker


class TestApplyDiffHandler:
    """Test cases for ApplyDiffHandler."""

    @pytest.fixture
    def history_tracker(self):
        """Create a history tracker for testing."""
        return InMemoryToolCallHistoryTracker()

    @pytest.fixture
    def handler(self, history_tracker):
        """Create an ApplyDiffHandler for testing."""
        return ApplyDiffHandler(history_tracker, rate_limit_window_seconds=60)

    def test_handler_properties(self, handler):
        """Test handler properties."""
        assert handler.name == "apply_diff_steering_handler"
        assert handler.priority == 100

    @pytest.mark.asyncio
    async def test_can_handle_apply_diff_tool(self, handler):
        """Test that handler can handle apply_diff tool calls."""
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        can_handle = await handler.can_handle(context)
        assert can_handle is True

    @pytest.mark.asyncio
    async def test_can_handle_different_tool(self, handler):
        """Test that handler cannot handle non-apply_diff tool calls."""
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="patch_file",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        can_handle = await handler.can_handle(context)
        assert can_handle is False

    @pytest.mark.asyncio
    async def test_handle_first_call_provides_steering(self, handler):
        """Test that first apply_diff call provides steering."""
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert "patch_file" in result.replacement_response
        assert "apply_diff" in result.replacement_response
        assert result.metadata is not None
        assert result.metadata["handler"] == "apply_diff_steering_handler"
        assert result.metadata["steering_type"] == "tool_preference"

    @pytest.mark.asyncio
    async def test_rate_limiting_within_window(self, handler):
        """Test that handler rate limits within the time window."""
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        # First call should provide steering
        result1 = await handler.handle(context)
        assert result1.should_swallow is True

        # Second call within rate limit window should not provide steering
        can_handle2 = await handler.can_handle(context)
        assert can_handle2 is False

    @pytest.mark.asyncio
    async def test_rate_limiting_after_window(self, handler):
        """Test that handler allows steering after rate limit window expires."""
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        # First call should provide steering
        result1 = await handler.handle(context)
        assert result1.should_swallow is True

        # Reset rate limit to simulate time passing
        handler.reset_rate_limit("test_session")

        # Second call should now provide steering again
        can_handle2 = await handler.can_handle(context)
        assert can_handle2 is True

        result2 = await handler.handle(context)
        assert result2.should_swallow is True

    @pytest.mark.asyncio
    async def test_rate_limiting_different_sessions(self, handler):
        """Test that rate limiting works per session."""
        context1 = ToolCallContext(
            session_id="session1",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        context2 = ToolCallContext(
            session_id="session2",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        # First call for session1 should provide steering
        result1 = await handler.handle(context1)
        assert result1.should_swallow is True

        # First call for session2 should also provide steering (different session)
        can_handle2 = await handler.can_handle(context2)
        assert can_handle2 is True

        result2 = await handler.handle(context2)
        assert result2.should_swallow is True

        # Second call for session1 should be rate limited
        can_handle3 = await handler.can_handle(context1)
        assert can_handle3 is False

    def test_get_reaction_config(self, handler):
        """Test getting reaction configuration."""
        config = handler.get_reaction_config()

        assert config.name == "apply_diff_steering_handler"
        assert config.config.tool_name_pattern == "apply_diff"
        assert config.config.mode.value == "active"
        assert config.config.rate_limit is not None
        assert config.config.rate_limit.calls_per_window == 1
        assert config.config.rate_limit.window_seconds == 60
        assert "patch_file" in config.steering_response.content

    def test_get_steering_stats_no_calls(self, handler):
        """Test getting steering stats for session with no calls."""
        stats = handler.get_steering_stats("test_session")

        assert stats["session_id"] == "test_session"
        assert stats["steering_count"] == 0
        assert stats["last_steering"] is None
        assert stats["can_steer_now"] is True

    @pytest.mark.asyncio
    async def test_get_steering_stats_with_calls(self, handler):
        """Test getting steering stats for session with calls."""
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        # Make a call
        await handler.handle(context)

        stats = handler.get_steering_stats("test_session")

        assert stats["session_id"] == "test_session"
        assert stats["steering_count"] == 1
        assert stats["last_steering"] is not None
        assert stats["can_steer_now"] is False  # Within rate limit window
        assert stats["rate_limit_window_seconds"] == 60

    def test_reset_rate_limit(self, handler):
        """Test resetting rate limit for a session."""
        # Set up rate limit state
        handler._last_steering_times["test_session"] = datetime.now()

        # Verify rate limited
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        # Should be rate limited
        assert asyncio.run(handler.can_handle(context)) is False

        # Reset rate limit
        handler.reset_rate_limit("test_session")

        # Should no longer be rate limited
        assert asyncio.run(handler.can_handle(context)) is True

    def test_custom_steering_message(self, history_tracker):
        """Test handler with custom steering message."""
        custom_message = "Custom steering message for apply_diff"
        handler = ApplyDiffHandler(
            history_tracker,
            steering_message=custom_message,
            rate_limit_window_seconds=30,
        )

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )

        result = asyncio.run(handler.handle(context))

        assert result.replacement_response == custom_message

    def test_different_rate_limit_windows(self, history_tracker):
        """Test handler with different rate limit windows."""
        handler = ApplyDiffHandler(history_tracker, rate_limit_window_seconds=30)

        config = handler.get_reaction_config()
        assert config.config.rate_limit.window_seconds == 30
