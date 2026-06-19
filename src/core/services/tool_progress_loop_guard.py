"""Session-level guard for cross-request tool-progress loops."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.tool_progress_loop import (
    ToolProgressLoopAction,
    ToolProgressLoopDecision,
    fingerprint_tool_call,
    fingerprint_tool_output,
)
from src.core.interfaces.tool_progress_loop_guard_interface import (
    IToolProgressLoopGuard,
)


@dataclass(slots=True)
class _SessionLoopState:
    consecutive_tool_followups: int = 0
    call_counts: OrderedDict[str, int] = field(default_factory=OrderedDict)
    output_counts: OrderedDict[str, int] = field(default_factory=OrderedDict)


class ToolProgressLoopGuard(IToolProgressLoopGuard):
    """Detects repeated tool calls/results before dispatching another backend request."""

    def __init__(
        self,
        *,
        max_consecutive_tool_followups: int = 50,
        max_repeated_tool_call_signature: int = 7,
        max_repeated_tool_output: int = 7,
        max_counts_per_session: int = 256,
        max_cached_sessions: int = 1000,
        enabled: bool = True,
    ) -> None:
        self._max_consecutive_tool_followups = max(1, max_consecutive_tool_followups)
        self._max_repeated_tool_call_signature = max(
            1, max_repeated_tool_call_signature
        )
        self._max_repeated_tool_output = max(1, max_repeated_tool_output)
        self._max_counts_per_session = max(1, max_counts_per_session)
        self._max_cached_sessions = max(1, max_cached_sessions)
        self._enabled = enabled
        self._sessions: OrderedDict[str, _SessionLoopState] = OrderedDict()

    async def evaluate_request(
        self,
        *,
        session_id: str,
        request: ChatRequest,
    ) -> ToolProgressLoopDecision:
        if not self._enabled:
            return ToolProgressLoopDecision(action=ToolProgressLoopAction.ALLOW)

        state = self._state_for(session_id)
        messages = list(getattr(request, "messages", []) or [])
        if self._has_new_user_message_after_last_tool(messages):
            state = _SessionLoopState()
            self._sessions[session_id] = state
            return ToolProgressLoopDecision(action=ToolProgressLoopAction.ALLOW)

        tool_outputs = self._extract_tool_outputs(messages)
        assistant_tool_calls = self._extract_recent_assistant_tool_calls(messages)
        if not tool_outputs:
            state.consecutive_tool_followups = 0
            return ToolProgressLoopDecision(action=ToolProgressLoopAction.ALLOW)

        state.consecutive_tool_followups += 1
        max_call_count = 0
        for tool_call in assistant_tool_calls:
            fp = fingerprint_tool_call(tool_call)
            key = fp.arguments_hash
            state.call_counts[key] = state.call_counts.get(key, 0) + 1
            max_call_count = max(max_call_count, state.call_counts[key])
            self._evict_oldest_if_needed(state.call_counts)

        max_output_count = 0
        for output in tool_outputs:
            output_fp = fingerprint_tool_output(output)
            key = output_fp.output_hash
            state.output_counts[key] = state.output_counts.get(key, 0) + 1
            max_output_count = max(max_output_count, state.output_counts[key])
            self._evict_oldest_if_needed(state.output_counts)

        if max_output_count >= self._max_repeated_tool_output:
            return ToolProgressLoopDecision(
                action=ToolProgressLoopAction.BLOCK,
                reason="repeated_tool_output",
                score=max_output_count,
                repeated_call_count=max_call_count,
                repeated_output_count=max_output_count,
            )

        if max_call_count >= self._max_repeated_tool_call_signature:
            return ToolProgressLoopDecision(
                action=ToolProgressLoopAction.BLOCK,
                reason="repeated_tool_call",
                score=max_call_count,
                repeated_call_count=max_call_count,
                repeated_output_count=max_output_count,
            )

        if state.consecutive_tool_followups >= self._max_consecutive_tool_followups:
            return ToolProgressLoopDecision(
                action=ToolProgressLoopAction.BLOCK,
                reason="consecutive_tool_followups",
                score=state.consecutive_tool_followups,
                repeated_call_count=max_call_count,
                repeated_output_count=max_output_count,
            )

        return ToolProgressLoopDecision(
            action=ToolProgressLoopAction.ALLOW,
            score=state.consecutive_tool_followups,
            repeated_call_count=max_call_count,
            repeated_output_count=max_output_count,
        )

    def _state_for(self, session_id: str) -> _SessionLoopState:
        state = self._sessions.get(session_id)
        if state is not None:
            self._sessions.move_to_end(session_id)
            return state
        while len(self._sessions) >= self._max_cached_sessions:
            self._sessions.popitem(last=False)
        state = _SessionLoopState()
        self._sessions[session_id] = state
        return state

    def _evict_oldest_if_needed(self, counter: OrderedDict[str, int]) -> None:
        while len(counter) > self._max_counts_per_session:
            counter.popitem(last=False)

    @staticmethod
    def _has_new_user_message_after_last_tool(messages: list[ChatMessage]) -> bool:
        last_tool_idx = -1
        last_user_idx = -1
        for idx, message in enumerate(messages):
            role = getattr(message, "role", None)
            if role == "tool":
                last_tool_idx = idx
            elif role == "user":
                last_user_idx = idx
        return last_tool_idx >= 0 and last_user_idx > last_tool_idx

    @staticmethod
    def _extract_tool_outputs(messages: list[ChatMessage]) -> list[Any]:
        outputs: list[Any] = []
        for message in reversed(messages):
            if getattr(message, "role", None) == "tool":
                outputs.append(getattr(message, "content", "") or "")
                continue
            if outputs:
                break
        outputs.reverse()
        return outputs

    @staticmethod
    def _extract_recent_assistant_tool_calls(messages: list[ChatMessage]) -> list[Any]:
        for message in reversed(messages):
            if getattr(message, "role", None) != "assistant":
                continue
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                return list(tool_calls)
        return []
