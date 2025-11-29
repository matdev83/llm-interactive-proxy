from __future__ import annotations

from typing import Any

import pytest
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    IToolCallHistoryTracker,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.tool_call_reactor_service import ToolCallReactorService


class _RecordingHistoryTracker(IToolCallHistoryTracker):
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    async def record_tool_call(
        self, session_id: str, tool_name: str, context: dict[str, Any]
    ) -> None:
        self.records.append((session_id, tool_name))

    async def get_call_count(
        self, session_id: str, tool_name: str, time_window_seconds: int
    ) -> int:
        return sum(
            1
            for recorded_session, recorded_tool in self.records
            if recorded_session == session_id and recorded_tool == tool_name
        )

    async def clear_history(self, session_id: str | None = None) -> None:
        if session_id is None:
            self.records.clear()
            return
        self.records = [record for record in self.records if record[0] != session_id]


class _PassthroughHandler(IToolCallHandler):
    def __init__(self) -> None:
        self.seen: list[ToolCallContext] = []

    @property
    def name(self) -> str:
        return "passthrough"

    @property
    def priority(self) -> int:
        return 0

    async def can_handle(self, context: ToolCallContext) -> bool:
        self.seen.append(context)
        return True

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        return ToolCallReactionResult(should_swallow=False)


@pytest.mark.asyncio
async def test_tool_call_reactor_aliases_empty_session_ids() -> None:
    tracker = _RecordingHistoryTracker()
    service = ToolCallReactorService(history_tracker=tracker)
    handler = _PassthroughHandler()
    await service.register_handler(handler)

    context_without_session = ToolCallContext(
        session_id="",
        backend_name="test-backend",
        model_name="model",
        full_response={},
        tool_name="dummy",
        tool_arguments={},
    )

    await service.process_tool_call(context_without_session)
    assert tracker.records
    alias_session_id = tracker.records[0][0]
    assert alias_session_id != ""

    await service.process_tool_call(context_without_session)
    assert tracker.records[1][0] != alias_session_id

    explicit_context = ToolCallContext(
        session_id="explicit-session",
        backend_name="test-backend",
        model_name="model",
        full_response={},
        tool_name="dummy",
        tool_arguments={},
    )
    await service.process_tool_call(explicit_context)
    assert tracker.records[2][0] == "explicit-session"


class MockToolCallHandler(IToolCallHandler):
    def __init__(
        self,
        name: str,
        priority: int = 0,
        can_handle_result: bool = True,
        handle_result: ToolCallReactionResult | None = None,
    ):
        self._name = name
        self._priority = priority
        self._can_handle_result = can_handle_result
        self._handle_result = handle_result or ToolCallReactionResult(
            should_swallow=False
        )
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
        return self._can_handle_result

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        self.handle_call_count += 1
        return self._handle_result


@pytest.fixture
def reactor() -> ToolCallReactorService:
    return ToolCallReactorService()


@pytest.mark.asyncio
async def test_handler_cache_invalidation_on_register(reactor: ToolCallReactorService):
    """Registering a new handler should rebuild cached ordering."""

    swallow_result = ToolCallReactionResult(should_swallow=True)
    low_priority_handler = MockToolCallHandler(
        "low_priority", priority=10, handle_result=swallow_result
    )
    await reactor.register_handler(low_priority_handler)

    context = ToolCallContext(
        session_id="test_session",
        backend_name="test_backend",
        model_name="test_model",
        full_response='{"content": "test"}',
        tool_name="test_tool",
        tool_arguments={"arg": "value"},
    )

    # Prime cached ordering with the existing handler
    result = await reactor.process_tool_call(context)
    assert result is not None
    assert low_priority_handler.handle_call_count == 1

    high_priority_handler = MockToolCallHandler(
        "high_priority",
        priority=100,
        handle_result=ToolCallReactionResult(should_swallow=True),
    )

    await reactor.register_handler(high_priority_handler)

    context2 = ToolCallContext(
        session_id="test_session",
        backend_name="test_backend",
        model_name="test_model",
        full_response='{"content": "test"}',
        tool_name="test_tool",
        tool_arguments={"arg": "value"},
    )

    result2 = await reactor.process_tool_call(context2)

    assert result2 is not None and result2.should_swallow is True
    assert high_priority_handler.handle_call_count == 1
    assert high_priority_handler.can_handle_call_count == 1
    # High priority handler should swallow before low priority handler is invoked again
    assert low_priority_handler.handle_call_count == 1


@pytest.mark.asyncio
async def test_handler_cache_invalidation_on_unregister(
    reactor: ToolCallReactorService,
):
    """Removing a handler should evict it from the cached ordering."""

    high_priority_handler = MockToolCallHandler(
        "high_priority",
        priority=100,
        handle_result=ToolCallReactionResult(should_swallow=True),
    )
    low_priority_handler = MockToolCallHandler(
        "low_priority",
        priority=10,
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

    # First call should be swallowed by the high priority handler
    result = await reactor.process_tool_call(context)
    assert result is not None and result.should_swallow is True
    assert high_priority_handler.handle_call_count == 1
    assert low_priority_handler.handle_call_count == 0

    await reactor.unregister_handler("high_priority")

    context2 = ToolCallContext(
        session_id="test_session",
        backend_name="test_backend",
        model_name="test_model",
        full_response='{"content": "test"}',
        tool_name="test_tool",
        tool_arguments={"arg": "value"},
    )

    result2 = await reactor.process_tool_call(context2)

    assert result2 is not None and result2.should_swallow is True
    # Low priority handler should now handle the call and high priority handler should not be invoked again
    assert low_priority_handler.handle_call_count == 1
    assert high_priority_handler.handle_call_count == 1
