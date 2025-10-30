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
    assert tracker.records[1][0] == alias_session_id

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
