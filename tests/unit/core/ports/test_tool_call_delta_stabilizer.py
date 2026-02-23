from __future__ import annotations

import pytest
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.ports.streaming_processors import ToolCallDeltaStabilizerProcessor


@pytest.mark.asyncio
async def test_tool_call_delta_stabilizer_fills_missing_id_and_name() -> None:
    proc = ToolCallDeltaStabilizerProcessor()

    first = StreamingContent(
        content="",
        is_done=False,
        metadata={
            "stream_id": "s1",
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": ""},
                }
            ],
        },
    )
    await proc.process(first)

    continuation = StreamingContent(
        content="",
        is_done=False,
        metadata={
            "stream_id": "s1",
            "tool_calls": [
                {
                    "index": 0,
                    "type": "function",
                    "function": {"arguments": "{"},
                }
            ],
        },
    )

    result = await proc.process(continuation)
    tool_call = result.metadata["tool_calls"][0]
    assert tool_call["id"] == "call_1"
    assert tool_call["function"]["name"] == "echo"


@pytest.mark.asyncio
async def test_tool_call_delta_stabilizer_clears_state_on_done() -> None:
    proc = ToolCallDeltaStabilizerProcessor()

    seed = StreamingContent(
        content="",
        is_done=False,
        metadata={
            "stream_id": "s1",
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": ""},
                }
            ],
        },
    )
    await proc.process(seed)

    done = StreamingContent(
        content="",
        is_done=True,
        metadata={"stream_id": "s1", "finish_reason": "tool_calls"},
    )
    await proc.process(done)

    after_done = StreamingContent(
        content="",
        is_done=False,
        metadata={
            "stream_id": "s1",
            "tool_calls": [
                {
                    "index": 0,
                    "type": "function",
                    "function": {"arguments": "{"},
                }
            ],
        },
    )
    result = await proc.process(after_done)

    tool_call = result.metadata["tool_calls"][0]
    assert "id" not in tool_call
    assert "name" not in tool_call.get("function", {})
