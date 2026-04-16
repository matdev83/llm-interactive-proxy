"""Unit tests for Codex websocket v2 lineage (vendored parity rules)."""

from __future__ import annotations

import pytest
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.continuation import (
    InMemoryCodexContinuationCoordinator,
)
from src.connectors.openai_codex.contracts import CodexRequestContext, ProcessedMessage
from src.connectors.openai_codex_v2.ws_lineage import CodexWebsocketV2Lineage
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def _ctx() -> CodexRequestContext:
    request = CanonicalChatRequest(
        model="gpt-5.4",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    return CodexRequestContext(
        request=request,
        processed_messages=[
            ProcessedMessage(role="user", content="hi", tool_calls=None)
        ],
        effective_model="gpt-5.4",
        capabilities=CodexClientCapabilities(),
        session_id="sess-ws-v2",
        metadata={
            "continuation_backend": "openai-codex-v2",
            "continuation_prompt_cache_key": "pk1",
        },
    )


@pytest.mark.asyncio
async def test_prepare_returns_false_when_no_lineage_entry_but_coordinator_has_id() -> (
    None
):
    coord = InMemoryCodexContinuationCoordinator()
    lineage = CodexWebsocketV2Lineage(coord)
    ctx = _ctx()
    await coord.record_turn(
        ctx,
        response_id="resp_prev",
        payload_dict={"input": [{"role": "user", "content": "a"}]},
    )
    full = {
        "model": "gpt-5.4",
        "input": [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        "instructions": None,
        "tools": [],
    }
    payload = dict(full)
    handled, _, _, _ = await lineage.try_prepare_websocket_continuation(
        continuation_context=ctx,
        payload_dict=payload,
        full_payload_dict=full,
    )
    assert handled is False


@pytest.mark.asyncio
async def test_delta_trims_input_on_prefix_extension() -> None:
    coord = InMemoryCodexContinuationCoordinator()
    lineage = CodexWebsocketV2Lineage(coord)
    ctx = _ctx()
    await coord.record_turn(
        ctx,
        response_id="resp1",
        payload_dict={"input": [{"role": "user", "content": "x"}]},
    )
    last_sent = {
        "model": "gpt-5.4",
        "input": [{"role": "user", "content": "x"}],
        "instructions": "sys",
        "tools": [{"type": "function", "name": "t"}],
    }
    await lineage.record_completed_websocket_turn(
        ctx,
        sent_payload=last_sent,
        response_id="resp1",
        items_added=[
            {"type": "message", "id": "m1", "role": "assistant", "content": "ok"}
        ],
    )
    full = {
        "model": "gpt-5.4",
        "input": [
            {"role": "user", "content": "x"},
            {"type": "message", "id": "m1", "role": "assistant", "content": "ok"},
            {"role": "user", "content": "next"},
        ],
        "instructions": "sys",
        "tools": [{"type": "function", "name": "t"}],
    }
    payload = dict(full)
    handled, out, reason, proxy = await lineage.try_prepare_websocket_continuation(
        continuation_context=ctx,
        payload_dict=payload,
        full_payload_dict=full,
    )
    assert handled is True
    assert proxy is True
    assert reason.startswith("ws_v2_delta")
    assert out["previous_response_id"] == "resp1"
    assert out["input"] == [{"role": "user", "content": "next"}]


@pytest.mark.asyncio
async def test_non_input_drift_forces_bootstrap() -> None:
    coord = InMemoryCodexContinuationCoordinator()
    lineage = CodexWebsocketV2Lineage(coord)
    ctx = _ctx()
    await coord.record_turn(
        ctx,
        response_id="resp1",
        payload_dict={"input": []},
    )
    await lineage.record_completed_websocket_turn(
        ctx,
        sent_payload={
            "model": "gpt-5.4",
            "input": [{"role": "user", "content": "x"}],
            "instructions": "A",
            "tools": [],
        },
        response_id="resp1",
        items_added=[],
    )
    full = {
        "model": "gpt-5.4",
        "input": [{"role": "user", "content": "x"}, {"role": "user", "content": "y"}],
        "instructions": "B",
        "tools": [],
    }
    payload = dict(full)
    handled, out, reason, proxy = await lineage.try_prepare_websocket_continuation(
        continuation_context=ctx,
        payload_dict=payload,
        full_payload_dict=full,
    )
    assert handled is True
    assert proxy is False
    assert "drift" in reason
    assert "previous_response_id" not in out
    assert out["input"] == full["input"]
