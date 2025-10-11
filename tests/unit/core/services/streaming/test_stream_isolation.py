from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import pytest

from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


@pytest.mark.asyncio
async def test_content_accumulation_isolates_parallel_streams() -> None:
    normalizer = StreamNormalizer([ContentAccumulationProcessor()])

    async def run_stream(chunks: list[str]) -> str:
        async def stream() -> AsyncGenerator[str, None]:
            for chunk in chunks:
                await asyncio.sleep(0)
                yield chunk
            await asyncio.sleep(0)
            yield b"data: [DONE]\n\n"

        collected: list[str] = []
        async for item in normalizer.process_stream(stream(), output_format="objects"):
            if item.content:
                collected.append(item.content)
        return "".join(collected)

    left, right = await asyncio.gather(
        run_stream(["alpha ", "beta"]),
        run_stream(["gamma ", "delta"]),
    )

    assert left == "alpha beta"
    assert right == "gamma delta"


@pytest.mark.asyncio
async def test_tool_call_repair_isolates_parallel_streams() -> None:
    repair_processor = ToolCallRepairProcessor(ToolCallRepairService())
    normalizer = StreamNormalizer([repair_processor])

    async def run_stream(name: str) -> dict[str, object]:
        async def stream() -> AsyncGenerator[str, None]:
            await asyncio.sleep(0)
            yield f'TOOL CALL: {name} {{"arg": 1}}'
            await asyncio.sleep(0)
            yield b"data: [DONE]\n\n"

        tool_calls: list[dict[str, object]] = []
        async for item in normalizer.process_stream(stream(), output_format="objects"):
            if not item.content:
                continue
            try:
                parsed = json.loads(item.content)
            except json.JSONDecodeError:
                continue
            if parsed.get("type") == "function":
                tool_calls.append(parsed)
        assert tool_calls, "Expected repaired tool call"
        return tool_calls[-1]

    first, second = await asyncio.gather(run_stream("first"), run_stream("second"))

    assert first["function"]["name"] == "first"
    assert second["function"]["name"] == "second"
