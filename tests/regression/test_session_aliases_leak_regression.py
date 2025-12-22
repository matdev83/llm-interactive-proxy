"""Regression test for ToolCallReactorService session aliases memory leak fix.

This test verifies that _session_aliases is properly initialized and cleaned up
to prevent unbounded memory growth. The fix ensures TTL-based cleanup and max
session aliases limit enforcement.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_reactor_service import ToolCallReactorService


class TestSessionAliasesLeakRegression:
    """Regression tests for ToolCallReactorService session aliases memory leak fix."""

    @pytest.fixture
    def reactor(self) -> ToolCallReactorService:
        """Create ToolCallReactorService instance with short TTL for testing."""
        return ToolCallReactorService(
            session_alias_ttl_seconds=1,  # 1 second TTL for testing
            max_session_aliases=100,  # Small limit for testing
        )

    def test_session_aliases_initialized(self, reactor: ToolCallReactorService) -> None:
        """Test that _session_aliases is properly initialized."""
        assert hasattr(reactor, "_session_aliases"), (
            "_session_aliases should be initialized in __init__"
        )
        assert hasattr(reactor, "_session_aliases_last_access"), (
            "_session_aliases_last_access should be initialized in __init__"
        )
        assert isinstance(reactor._session_aliases, dict), (
            "_session_aliases should be a dict"
        )
        assert isinstance(reactor._session_aliases_last_access, dict), (
            "_session_aliases_last_access should be a dict"
        )

    @pytest.mark.asyncio
    async def test_session_aliases_no_attribute_error(
        self, reactor: ToolCallReactorService
    ) -> None:
        """Test that processing tool calls doesn't raise AttributeError."""
        context = ToolCallContext(
            session_id="test_session_123",
            backend_name="test_backend",
            model_name="test_model",
            full_response=None,
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
            calling_agent="test_agent",
            timestamp=datetime.now(timezone.utc),
        )

        # Should not raise AttributeError
        try:
            await reactor.process_tool_call(context)
        except AttributeError as e:
            pytest.fail(f"AttributeError raised: {e}")

        # Verify entry was created
        assert "test_session_123" in reactor._session_aliases, (
            "Session alias entry should be created"
        )
        assert "test_session_123" in reactor._session_aliases_last_access, (
            "Session alias last access should be tracked"
        )

    @pytest.mark.asyncio
    async def test_max_session_aliases_limit_enforced(
        self, reactor: ToolCallReactorService
    ) -> None:
        """Test that max_session_aliases limit is enforced."""
        # Create more sessions than the limit
        num_sessions = 150  # More than max_session_aliases (100)

        for i in range(num_sessions):
            context = ToolCallContext(
                session_id=f"session_{i}",
                backend_name="test_backend",
                model_name="test_model",
                full_response=None,
                tool_name="test_tool",
                tool_arguments={"arg": f"value_{i}"},
                calling_agent="test_agent",
                timestamp=datetime.now(timezone.utc),
            )
            await reactor.process_tool_call(context)

        # Check that size is limited
        size = len(reactor._session_aliases)
        assert size <= reactor._max_session_aliases, (
            f"Size should be <= {reactor._max_session_aliases}, got {size}. "
            "Max session aliases limit is not being enforced."
        )

    @pytest.mark.asyncio
    async def test_session_aliases_ttl_cleanup(
        self, reactor: ToolCallReactorService
    ) -> None:
        """Test that expired session aliases are cleaned up based on TTL."""
        # Create an entry
        context = ToolCallContext(
            session_id="old_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response=None,
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
            calling_agent="test_agent",
            timestamp=datetime.now(timezone.utc),
        )
        await reactor.process_tool_call(context)
        assert "old_session" in reactor._session_aliases, (
            "Session alias should be created"
        )

        # Manually set last_access to be old (expired)
        reactor._session_aliases_last_access["old_session"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=2)  # Older than TTL (1 second)

        # Process another call to trigger cleanup
        new_context = ToolCallContext(
            session_id="new_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response=None,
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
            calling_agent="test_agent",
            timestamp=datetime.now(timezone.utc),
        )
        await reactor.process_tool_call(new_context)

        # Old session should be cleaned up
        assert "old_session" not in reactor._session_aliases, (
            "Expired session alias should be cleaned up"
        )
        assert "old_session" not in reactor._session_aliases_last_access, (
            "Expired session alias last access should be cleaned up"
        )
        assert "new_session" in reactor._session_aliases, (
            "New session alias should still exist"
        )

    @pytest.mark.asyncio
    async def test_session_aliases_bounded_growth(
        self, reactor: ToolCallReactorService
    ) -> None:
        """Test that session aliases don't grow unbounded."""
        # Create many unique sessions
        num_sessions = 10000

        for i in range(num_sessions):
            context = ToolCallContext(
                session_id=f"session_{i}",
                backend_name="test_backend",
                model_name="test_model",
                full_response=None,
                tool_name="test_tool",
                tool_arguments={"arg": f"value_{i}"},
                calling_agent="test_agent",
                timestamp=datetime.now(timezone.utc),
            )
            await reactor.process_tool_call(context)

        # Check that size is bounded
        size = len(reactor._session_aliases)
        assert size <= reactor._max_session_aliases, (
            f"Session aliases grew unbounded: {size} entries (max: {reactor._max_session_aliases}). "
            "Memory leak fix is not working."
        )

    @pytest.mark.asyncio
    async def test_session_aliases_cleanup_on_every_call(
        self, reactor: ToolCallReactorService
    ) -> None:
        """Test that cleanup is called on every process_tool_call invocation."""
        # Create many sessions to fill up to limit
        for i in range(reactor._max_session_aliases):
            context = ToolCallContext(
                session_id=f"session_{i}",
                backend_name="test_backend",
                model_name="test_model",
                full_response=None,
                tool_name="test_tool",
                tool_arguments={"arg": f"value_{i}"},
                calling_agent="test_agent",
                timestamp=datetime.now(timezone.utc),
            )
            await reactor.process_tool_call(context)

        initial_size = len(reactor._session_aliases)
        assert initial_size == reactor._max_session_aliases, (
            f"Should have {reactor._max_session_aliases} sessions, got {initial_size}"
        )

        # Add one more session - should trigger cleanup and evict oldest
        new_context = ToolCallContext(
            session_id="new_session_after_limit",
            backend_name="test_backend",
            model_name="test_model",
            full_response=None,
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
            calling_agent="test_agent",
            timestamp=datetime.now(timezone.utc),
        )
        await reactor.process_tool_call(new_context)

        # Size should still be at limit
        final_size = len(reactor._session_aliases)
        assert final_size <= reactor._max_session_aliases, (
            f"Size should be <= {reactor._max_session_aliases} after cleanup, got {final_size}"
        )
        assert "new_session_after_limit" in reactor._session_aliases, (
            "New session should be added"
        )
