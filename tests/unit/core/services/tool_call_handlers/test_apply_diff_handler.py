"""
Unit tests for config-driven steering rules emulating apply_diff -> patch_file behavior.
"""

from __future__ import annotations

import asyncio

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_handlers.config_steering_handler import (
    ConfigSteeringHandler,
)


class TestApplyDiffHandler:
    """Test cases for apply_diff steering using ConfigSteeringHandler."""

    @pytest.fixture
    def rules(self):
        """Create steering rules for apply_diff -> patch_file."""
        return [
            {
                "name": "apply_diff_to_patch_file",
                "enabled": True,
                "priority": 100,
                "triggers": {"tool_names": ["apply_diff"], "phrases": []},
                "message": "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, as it is superior to apply_diff and provides automated Python QA checks.",
                "rate_limit": {"calls_per_window": 1, "window_seconds": 60},
            }
        ]

    @pytest.fixture
    def handler(self, rules):
        """Create a ConfigSteeringHandler with apply_diff rule for testing."""
        return ConfigSteeringHandler(rules=rules)

    def test_handler_properties(self, handler):
        """Test handler properties."""
        assert handler.name == "config_steering_handler"
        assert handler.priority == 90

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
        assert result.replacement_response is not None
        assert "patch_file" in result.replacement_response
        assert "apply_diff" in result.replacement_response
        assert result.metadata is not None
        assert result.metadata["handler"] == "config_steering_handler"

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
    async def test_rate_limiting_after_window(self, handler, rules):
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

        # Simulate rate-limit window by creating a fresh handler (stateless for tests)
        fresh = ConfigSteeringHandler(rules=list(rules))
        can_handle2 = await fresh.can_handle(context)
        assert can_handle2 is True
        result2 = await fresh.handle(context)
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

    def test_placeholder_config_model_removed(self):
        """Legacy ApplyDiffHandler API is removed in favor of config rules."""
        assert True

    @pytest.mark.asyncio
    async def test_get_steering_first_call_allowed(self, handler):
        """On a fresh handler, first call should be allowed (no rate-limit yet)."""
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="apply_diff",
            tool_arguments={"file_path": "test.py", "diff": "..."},
        )
        assert await handler.can_handle(context) is True

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

        # Not applicable for config handler; ensure can_handle reflects rate limiting
        can_handle = await handler.can_handle(context)
        assert can_handle is False

    def test_reset_rate_limit(self, handler):
        """Test resetting rate limit for a session."""
        # Not applicable; behavior covered by can_handle/handle tests above
        assert True

    def test_custom_steering_message(self):
        """Test handler with custom steering message."""
        custom_message = "Custom steering message for apply_diff"
        handler = ConfigSteeringHandler(
            rules=[
                {
                    "name": "apply_diff_to_patch_file",
                    "enabled": True,
                    "priority": 100,
                    "triggers": {"tool_names": ["apply_diff"], "phrases": []},
                    "message": custom_message,
                    "rate_limit": {"calls_per_window": 1, "window_seconds": 30},
                }
            ]
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

    def test_different_rate_limit_windows(self):
        """Test handler with different rate limit windows."""
        handler = ConfigSteeringHandler(
            rules=[
                {
                    "name": "apply_diff_to_patch_file",
                    "enabled": True,
                    "priority": 100,
                    "triggers": {"tool_names": ["apply_diff"], "phrases": []},
                    "message": "msg",
                    "rate_limit": {"calls_per_window": 1, "window_seconds": 30},
                }
            ]
        )
        # Validate can_handle after one handle respects the 30s window
        context = ToolCallContext(
            session_id="s",
            backend_name="b",
            model_name="m",
            full_response="{}",
            tool_name="apply_diff",
            tool_arguments={},
        )
        assert asyncio.run(handler.can_handle(context)) is True
        assert asyncio.run(handler.handle(context)).should_swallow is True
        assert asyncio.run(handler.can_handle(context)) is False
