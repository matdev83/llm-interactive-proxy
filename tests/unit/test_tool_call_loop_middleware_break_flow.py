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


def _response_with_tool_call(name: str, args: dict) -> ProcessedResponse:
    payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    ]
                }
            }
        ]
    }
    return ProcessedResponse(content=json.dumps(payload))


@pytest.mark.asyncio
async def test_tool_call_loop_cancellation_then_break() -> None:
    mw = ToolCallLoopDetectionMiddleware()
    cfg = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=4,
    )
    ctx = {"config": cfg}
    sid = "s1"

    # Send 4 identical calls -> expect loop error on the 4th
    for _ in range(3):
        await mw.process(_response_with_tool_call("hello", {"x": 1}), sid, ctx)

    with pytest.raises(ToolCallLoopError):
        await mw.process(_response_with_tool_call("hello", {"x": 1}), sid, ctx)

    # Next identical call should also be blocked (break)
    with pytest.raises(ToolCallLoopError):
        await mw.process(_response_with_tool_call("hello", {"x": 1}), sid, ctx)
