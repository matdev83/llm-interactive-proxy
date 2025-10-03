"""
Unit tests for Tool Call Reactor Service.
"""

from __future__ import annotations

import asyncio

import pytest
from src.core.common.exceptions import ToolCallReactorError
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.tool_call_reactor_service import (
    InMemoryToolCallHistoryTracker,
    ToolCallReactorService,
)


class MockToolCallHandler(IToolCallHandler):
    """Mock implementation of IToolCallHandler for testing."""

    def __init__(
        self,
        name: str,
        priority: int = 0,
        can_handle_return: bool = True,
        handle_result: ToolCallReactionResult | None = None,
    ):
        self._name = name
        self._priority = priority
        self._can_handle_return = can_handle_return
        self._handle_result = handle_result
        self.can_handle_call_count = 0
        self.handle_call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def can_handle(self, context: ToolCallContext) -> bool:
        self.can_handle_call_count += 1
        return self._can_handle_return

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        self.handle_call_count += 1
        if self._handle_result:
            return self._handle_result
        return ToolCallReactionResult(should_swallow=False)


class TestToolCallReactorService:
    """Test cases for ToolCallReactorService."""

    @pytest.fixture
    def history_tracker(self):
        """Create a history tracker for testing."""
        return InMemoryToolCallHistoryTracker()

    @pytest.fixture
    def reactor(self, history_tracker):
        """Create a reactor service for testing."""
        return ToolCallReactorService(history_tracker)

    @pytest.mark.asyncio
    async def test_register_handler_success(self, reactor):
        """Test successful handler registration."""
        handler = MockToolCallHandler("test_handler")

        await reactor.register_handler(handler)

        handlers = reactor.get_registered_handlers()
        assert "test_handler" in handlers
        assert len(handlers) == 1

    @pytest.mark.asyncio
    async def test_register_handler_duplicate_name(self, reactor):
        """Test registering handler with duplicate name raises error."""
        handler1 = MockToolCallHandler("test_handler")
        handler2 = MockToolCallHandler("test_handler")

        await reactor.register_handler(handler1)

        with pytest.raises(ToolCallReactorError, match="already registered"):
            await reactor.register_handler(handler2)

    @pytest.mark.asyncio
    async def test_unregister_handler_success(self, reactor):
        """Test successful handler unregistration."""
        handler = MockToolCallHandler("test_handler")
        await reactor.register_handler(handler)

        await reactor.unregister_handler("test_handler")

        handlers = reactor.get_registered_handlers()
        assert "test_handler" not in handlers
        assert len(handlers) == 0

    @pytest.mark.asyncio
    async def test_unregister_handler_not_found(self, reactor):
        """Test unregistering non-existent handler raises error."""
        with pytest.raises(ToolCallReactorError, match="not registered"):
            await reactor.unregister_handler("non_existent")

    @pytest.mark.asyncio
    async def test_process_tool_call_no_handlers(self, reactor):
        """Test processing tool call with no registered handlers."""
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
        )

        result = await reactor.process_tool_call(context)

        assert result is None

    @pytest.mark.asyncio
    async def test_process_tool_call_handler_can_handle_false(self, reactor):
        """Test processing tool call when handler cannot handle it."""
        handler = MockToolCallHandler("test_handler", can_handle_return=False)
        await reactor.register_handler(handler)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
        )

        result = await reactor.process_tool_call(context)

        assert result is None
        assert handler.can_handle_call_count == 1
        assert handler.handle_call_count == 0

    @pytest.mark.asyncio
    async def test_process_tool_call_handler_swallows_call(self, reactor):
        """Test processing tool call when handler swallows it."""
        swallow_result = ToolCallReactionResult(
            should_swallow=True,
            replacement_response="steering message",
            metadata={"test": "metadata"},
        )
        handler = MockToolCallHandler(
            "test_handler", can_handle_return=True, handle_result=swallow_result
        )
        await reactor.register_handler(handler)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
        )

        result = await reactor.process_tool_call(context)

        assert result is not None
        assert result.should_swallow is True
        assert result.replacement_response == "steering message"
        assert result.metadata == {"test": "metadata"}
        assert handler.can_handle_call_count == 1
        assert handler.handle_call_count == 1

    @pytest.mark.asyncio
    async def test_process_tool_call_multiple_handlers_priority(self, reactor):
        """Test processing tool call with multiple handlers respects priority."""
        # High priority handler that doesn't swallow
        high_priority_handler = MockToolCallHandler(
            "high_priority",
            priority=100,
            can_handle_return=True,
            handle_result=ToolCallReactionResult(should_swallow=False),
        )

        # Low priority handler that swallows
        low_priority_handler = MockToolCallHandler(
            "low_priority",
            priority=10,
            can_handle_return=True,
            handle_result=ToolCallReactionResult(should_swallow=True),
        )

        await reactor.register_handler(low_priority_handler)
        await reactor.register_handler(high_priority_handler)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
        )

        result = await reactor.process_tool_call(context)

        # High priority handler should be checked first, and since it doesn't swallow,
        # low priority handler should be checked and should swallow
        assert result is not None
        assert result.should_swallow is True
        assert low_priority_handler.handle_call_count == 1
        assert high_priority_handler.can_handle_call_count == 1
        assert high_priority_handler.handle_call_count == 1
        assert low_priority_handler.can_handle_call_count == 1
        assert low_priority_handler.handle_call_count == 1

    @pytest.mark.asyncio
    async def test_process_tool_call_handler_error_handling(self, reactor):
        """Test that handler errors don't crash the reactor."""

        async def failing_can_handle(context):
            raise Exception("Handler error")

        handler = MockToolCallHandler("failing_handler")
        handler.can_handle = failing_can_handle

        await reactor.register_handler(handler)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="test_tool",
            tool_arguments={"arg": "value"},
        )

        # Should not raise exception
        result = await reactor.process_tool_call(context)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_registered_handlers(self, reactor):
        """Test getting list of registered handler names."""
        handler1 = MockToolCallHandler("handler1")
        handler2 = MockToolCallHandler("handler2")

        await reactor.register_handler(handler1)
        await reactor.register_handler(handler2)

        handlers = reactor.get_registered_handlers()

        assert len(handlers) == 2
        assert "handler1" in handlers
        assert "handler2" in handlers


class TestInMemoryToolCallHistoryTracker:
    """Test cases for InMemoryToolCallHistoryTracker."""

    @pytest.fixture
    def tracker(self):
        """Create a history tracker for testing."""
        return InMemoryToolCallHistoryTracker()

    @pytest.mark.asyncio
    async def test_record_tool_call(self, tracker):
        """Test recording a tool call."""
        await tracker.record_tool_call(
            session_id="test_session",
            tool_name="test_tool",
            context={"arg": "value", "timestamp": 1234567890},
        )

        # Verify call was recorded
        call_count = await tracker.get_call_count("test_session", "test_tool", 3600)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_get_call_count_time_window(self, tracker):
        """Test getting call count within time window."""
        current_time = asyncio.get_event_loop().time()

        # Record calls at different times
        await tracker.record_tool_call(
            "session1", "tool1", {"timestamp": current_time - 100}
        )
        await tracker.record_tool_call(
            "session1", "tool1", {"timestamp": current_time - 50}
        )
        await tracker.record_tool_call(
            "session1", "tool1", {"timestamp": current_time - 10}
        )

        # Count calls within last 60 seconds
        count = await tracker.get_call_count("session1", "tool1", 60)
        assert count == 2  # Should include calls at -50s and -10s

        # Count calls within last 30 seconds
        count = await tracker.get_call_count("session1", "tool1", 30)
        assert count == 1  # Should only include call at -10s

    @pytest.mark.asyncio
    async def test_get_call_count_different_sessions(self, tracker):
        """Test call counting for different sessions."""
        current_time = asyncio.get_event_loop().time()
        await tracker.record_tool_call(
            "session1", "tool1", {"timestamp": current_time - 100}
        )
        await tracker.record_tool_call(
            "session2", "tool1", {"timestamp": current_time - 100}
        )

        count1 = await tracker.get_call_count("session1", "tool1", 3600)
        count2 = await tracker.get_call_count("session2", "tool1", 3600)

        assert count1 == 1
        assert count2 == 1

    @pytest.mark.asyncio
    async def test_clear_history_all_sessions(self, tracker):
        """Test clearing all history."""
        current_time = asyncio.get_event_loop().time()
        await tracker.record_tool_call(
            "session1", "tool1", {"timestamp": current_time - 100}
        )
        await tracker.record_tool_call(
            "session2", "tool1", {"timestamp": current_time - 100}
        )

        await tracker.clear_history()

        count1 = await tracker.get_call_count("session1", "tool1", 3600)
        count2 = await tracker.get_call_count("session2", "tool1", 3600)

        assert count1 == 0
        assert count2 == 0

    @pytest.mark.asyncio
    async def test_clear_history_specific_session(self, tracker):
        """Test clearing history for specific session."""
        current_time = asyncio.get_event_loop().time()
        await tracker.record_tool_call(
            "session1", "tool1", {"timestamp": current_time - 100}
        )
        await tracker.record_tool_call(
            "session2", "tool1", {"timestamp": current_time - 100}
        )

        await tracker.clear_history("session1")

        count1 = await tracker.get_call_count("session1", "tool1", 3600)
        count2 = await tracker.get_call_count("session2", "tool1", 3600)

        assert count1 == 0
        assert count2 == 1
