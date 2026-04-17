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
async def test_prepare_bootstraps_without_previous_response_id_when_lineage_missing() -> (
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
    handled, out, reason, proxy = await lineage.try_prepare_websocket_continuation(
        continuation_context=ctx,
        payload_dict=payload,
        full_payload_dict=full,
    )
    assert handled is True
    assert proxy is False
    assert reason == "ws_v2_full_bootstrap_no_lineage"
    assert "previous_response_id" not in out
    assert out["input"] == full["input"]


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


@pytest.mark.asyncio
async def test_multi_turn_delta_requires_full_logical_last_sent() -> None:
    """Wire-only delta in lineage breaks turn 3+; full logical input preserves deltas."""
    coord = InMemoryCodexContinuationCoordinator()
    lineage = CodexWebsocketV2Lineage(coord)
    ctx = _ctx()
    u1 = {"role": "user", "content": "a"}
    m1 = {"type": "message", "id": "m1", "role": "assistant", "content": "A"}
    u2 = {"role": "user", "content": "b"}
    m2 = {"type": "message", "id": "m2", "role": "assistant", "content": "B"}
    u3 = {"role": "user", "content": "c"}
    tools = [{"type": "function", "name": "t"}]
    base = {"model": "gpt-5.4", "instructions": "sys", "tools": tools}

    await coord.record_turn(ctx, response_id="resp1", payload_dict={"input": [u1]})
    await lineage.record_completed_websocket_turn(
        ctx,
        sent_payload={**base, "input": [u1]},
        response_id="resp1",
        items_added=[m1],
    )
    full2 = {**base, "input": [u1, m1, u2]}
    p2 = dict(full2)
    handled2, out2, reason2, proxy2 = await lineage.try_prepare_websocket_continuation(
        continuation_context=ctx,
        payload_dict=p2,
        full_payload_dict=full2,
    )
    assert handled2 and proxy2 and reason2.startswith("ws_v2_delta")
    assert out2["input"] == [u2]

    await coord.record_turn(
        ctx,
        response_id="resp2",
        payload_dict={"input": [u1, m1, u2]},
    )
    # Bug-shaped record: only the wire suffix — turn 3 cannot match prefix.
    await lineage.record_completed_websocket_turn(
        ctx,
        sent_payload={**base, "input": [u2]},
        response_id="resp2",
        items_added=[m2],
    )
    full3 = {**base, "input": [u1, m1, u2, m2, u3]}
    p3 = dict(full3)
    handled3, out3, reason3, proxy3 = await lineage.try_prepare_websocket_continuation(
        continuation_context=ctx,
        payload_dict=p3,
        full_payload_dict=full3,
    )
    assert handled3 and proxy3 is False
    assert "prefix" in reason3
    assert out3["input"] == full3["input"]

    # Prefix mismatch invalidates coordinator + lineage; re-seed like a new turn.
    await coord.record_turn(
        ctx,
        response_id="resp2",
        payload_dict={"input": [u1, m1, u2]},
    )
    # Correct-shaped record: full logical input for turn 2.
    await lineage.record_completed_websocket_turn(
        ctx,
        sent_payload={**base, "input": [u1, m1, u2]},
        response_id="resp2",
        items_added=[m2],
    )
    p3b = dict(full3)
    handled3b, out3b, reason3b, proxy3b = (
        await lineage.try_prepare_websocket_continuation(
            continuation_context=ctx,
            payload_dict=p3b,
            full_payload_dict=full3,
        )
    )
    assert handled3b and proxy3b and reason3b.startswith("ws_v2_delta")
    assert out3b["previous_response_id"] == "resp2"
    assert out3b["input"] == [u3]


@pytest.mark.asyncio
async def test_delta_accepts_canonicalized_prefix_for_raw_ws_output_items() -> None:
    """Canonical history replay omits volatile WS-only fields like ids/status."""
    coord = InMemoryCodexContinuationCoordinator()
    lineage = CodexWebsocketV2Lineage(coord)
    ctx = _ctx()
    u1 = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "a"}],
    }
    raw_function_call = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "number_lab",
        "arguments": '{"numbers":[1],"operation":"sum"}',
        "status": "completed",
    }
    raw_assistant_message = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [
            {
                "type": "output_text",
                "text": "The total is 1.",
                "annotations": [],
            }
        ],
    }
    u2 = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "next"}],
    }
    base = {"model": "gpt-5.4", "instructions": "sys", "tools": []}

    await coord.record_turn(ctx, response_id="resp1", payload_dict={"input": [u1]})
    await lineage.record_completed_websocket_turn(
        ctx,
        sent_payload={**base, "input": [u1]},
        response_id="resp1",
        items_added=[raw_function_call, raw_assistant_message],
    )

    canonical_followup = {
        **base,
        "input": [
            u1,
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "number_lab",
                "arguments": '{\n  "numbers": [1],\n  "operation": "sum"\n}',
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "The total is 1."}],
            },
            u2,
        ],
    }
    payload = dict(canonical_followup)

    handled, out, reason, proxy = await lineage.try_prepare_websocket_continuation(
        continuation_context=ctx,
        payload_dict=payload,
        full_payload_dict=canonical_followup,
    )

    assert handled is True
    assert proxy is True
    assert reason.startswith("ws_v2_delta")
    assert out["previous_response_id"] == "resp1"
    assert out["input"] == [u2]


@pytest.mark.asyncio
async def test_non_text_message_parts_do_not_false_match_prefix() -> None:
    coord = InMemoryCodexContinuationCoordinator()
    lineage = CodexWebsocketV2Lineage(coord)
    ctx = _ctx()
    u1 = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "describe image"}],
    }
    raw_assistant_message = {
        "type": "message",
        "id": "msg_img_1",
        "role": "assistant",
        "status": "completed",
        "content": [
            {
                "type": "input_image",
                "image_url": "file://first-image.png",
                "detail": "high",
            }
        ],
    }
    changed_assistant_message = {
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "input_image",
                "image_url": "file://different-image.png",
                "detail": "high",
            }
        ],
    }
    u2 = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "continue"}],
    }
    base = {"model": "gpt-5.4", "instructions": "sys", "tools": []}

    await coord.record_turn(ctx, response_id="resp1", payload_dict={"input": [u1]})
    await lineage.record_completed_websocket_turn(
        ctx,
        sent_payload={**base, "input": [u1]},
        response_id="resp1",
        items_added=[raw_assistant_message],
    )

    followup = {**base, "input": [u1, changed_assistant_message, u2]}
    payload = dict(followup)

    handled, out, reason, proxy = await lineage.try_prepare_websocket_continuation(
        continuation_context=ctx,
        payload_dict=payload,
        full_payload_dict=followup,
    )

    assert handled is True
    assert proxy is False
    assert "prefix" in reason
    assert "previous_response_id" not in out
    assert out["input"] == followup["input"]
