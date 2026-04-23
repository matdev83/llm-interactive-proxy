"""Regression: proxy-side stalls on long ``http_full_replay`` Codex sessions.

Historically, two issues showed up together with ``Observed Codex response id`` / long
histories:

1. ``record_turn`` fingerprinted the entire ``input`` list synchronously on the event
   loop (``json.dumps`` per item), freezing the process under large replays.

2. ``ResponseExecutor._log_request_attempt`` computed ``input_bytes`` / ``tools_bytes``
   via a full ``json.dumps`` of the entire payload for INFO logs before each upstream
   request, which could take multiple seconds for hundreds of messages.

Upstream Codex can still pause between SSE events; these tests only guard the proxy.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.continuation import (
    InMemoryCodexContinuationCoordinator,
    _build_codex_turn_snapshot,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    ProcessedMessage,
)
from src.connectors.openai_codex.executor import ResponseExecutor
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def _codex_context(session_id: str) -> CodexRequestContext:
    request = CanonicalChatRequest(
        model="gpt-5.1-codex",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
    )
    return CodexRequestContext(
        request=request,
        processed_messages=[ProcessedMessage(role="user", content="hello")],
        effective_model="gpt-5.1-codex",
        capabilities=CodexClientCapabilities(),
        session_id=session_id,
        metadata={
            "continuation_backend": "openai-codex",
            "continuation_prompt_cache_key": "prompt-a",
        },
    )


@pytest.mark.asyncio
async def test_record_turn_fingerprints_large_input_via_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    context = _codex_context("session-regression-large-input")
    big_input = [
        {"type": "message", "role": "user", "content": f"line-{i}"} for i in range(250)
    ]

    to_thread_calls: list[Any] = []

    real_to_thread = asyncio.to_thread

    async def _spy_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        to_thread_calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(
        "src.connectors.openai_codex.continuation.asyncio.to_thread",
        _spy_to_thread,
    )

    await coordinator.record_turn(
        context,
        response_id="resp-regression",
        payload_dict={
            "input": big_input,
            "instructions": "inst",
            "tools": [{"type": "function", "name": "read", "parameters": {}}],
        },
    )

    assert to_thread_calls == [_build_codex_turn_snapshot]
    snapshot = await coordinator.get_snapshot(context)
    assert snapshot is not None
    assert snapshot.response_id == "resp-regression"
    assert len(snapshot.input_fingerprints) == 250


def test_measure_json_bytes_for_log_skips_long_lists(
    executor: ResponseExecutor,
) -> None:
    """INFO-only size metrics must not full-serialize huge ``input`` lists."""
    cap = executor._LOG_JSON_MEASURE_MAX_INPUT_ITEMS
    assert (
        executor._measure_json_bytes_for_log([{"i": n} for n in range(cap + 1)]) is None
    )
    measured = executor._measure_json_bytes_for_log([{"i": n} for n in range(5)])
    assert isinstance(measured, int)
    assert measured > 0
