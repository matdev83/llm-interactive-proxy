from __future__ import annotations

import json

import pytest
from src.core.common.exceptions import ToolCallLoopError
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.tool_call_loop_middleware import (
    ToolCallLoopDetectionMiddleware,
)
from src.tool_call_loop.config import ToolLoopMode


def _payload(name: str, args: dict) -> str:
    return json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(args),
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_chance_then_break_flow() -> None:
    mw = ToolCallLoopDetectionMiddleware()
    cfg = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=4,
        tool_loop_mode=ToolLoopMode.CHANCE_THEN_BREAK,
    )
    ctx = {"config": cfg}
    sid = "sess"

    # Warm-up to 3 repeats
    for _ in range(3):
        await mw.process(
            ProcessedResponse(content=_payload("calc", {"x": 1})), sid, ctx
        )

    # 4th repeat should raise with guidance (first chance)
    with pytest.raises(ToolCallLoopError) as e1:
        await mw.process(
            ProcessedResponse(content=_payload("calc", {"x": 1})), sid, ctx
        )
    assert "warning" in str(e1.value).lower() or "will be stopped" in str(e1.value)

    # Next identical call should raise with after-guidance message (hard break)
    with pytest.raises(ToolCallLoopError) as e2:
        await mw.process(
            ProcessedResponse(content=_payload("calc", {"x": 1})), sid, ctx
        )
    assert "after guidance" in str(e2.value).lower()
