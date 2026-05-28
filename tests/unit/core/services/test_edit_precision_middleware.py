from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.edit_precision_middleware import EditPrecisionTuningMiddleware


@pytest.mark.asyncio
async def test_tuning_middleware_detects_opencode_apply_patch_failure_in_tool_message() -> (
    None
):
    request = ChatRequest(
        model="openai-codex",
        messages=[
            ChatMessage(role="user", content="Please update the strategy file."),
            ChatMessage(
                role="tool",
                content=(
                    "apply_patch verification failed: Error: Failed to find "
                    "expected lines in "
                    "C:\\Users\\Mateusz\\source\\repos\\vbt-strategy-lab\\src\\"
                    "vbt_strategy_lab\\strategies\\faber_ath_midcap_breakout.py:\n"
                    '        f"trail={params.position_trail_mode}|"'
                ),
                tool_call_id="call_patch",
            ),
        ],
        temperature=0.7,
        top_p=0.9,
    )

    middleware = EditPrecisionTuningMiddleware(
        target_temperature=0.1,
        min_top_p=0.3,
    )

    tuned = await middleware.process(request, context={"session_id": "sess-opencode"})

    assert tuned.temperature == pytest.approx(0.0)
    assert tuned.top_p == pytest.approx(0.3)
    assert tuned.extra_body is not None
    assert tuned.extra_body["_edit_precision_mode"] is True
    meta = tuned.extra_body["_edit_precision_meta"]
    assert meta["original_temperature"] == pytest.approx(0.7)
    assert meta["applied_temperature"] == pytest.approx(0.0)
