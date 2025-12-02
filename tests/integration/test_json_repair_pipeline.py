from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.json_repair_processor import JsonRepairProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


def _content_to_text(content: str | dict[str, Any] | bytes | None) -> str:
    if isinstance(content, bytes):
        return content.decode("utf-8", "ignore")
    if isinstance(content, dict):
        return json.dumps(content, sort_keys=True)
    return content or ""


@pytest.mark.asyncio
async def test_json_repair_and_tool_call_repair_together_objects() -> None:
    """Test that JSON repair works alongside ToolCallRepairProcessor.

    Note: ToolCallRepairProcessor is now a transparent pass-through
    (virtual tool call detection was disabled). This test verifies that:
    1. JSON repair still works correctly
    2. The processors can be chained without errors
    3. Content passes through unchanged (no tool call extraction)
    """
    # Build processors: JSON repair first, then tool call repair
    json_proc = JsonRepairProcessor(
        repair_service=JsonRepairService(),
        buffer_cap_bytes=4096,
        strict_mode=False,
    )
    tool_proc = ToolCallRepairProcessor(ToolCallRepairService())
    # Include accumulation to preserve content
    normalizer = StreamNormalizer(
        [json_proc, tool_proc, ContentAccumulationProcessor()]
    )

    # Create stream with malformed JSON and a textual tool call
    async def stream() -> AsyncGenerator[object, None]:
        yield "prefix "
        yield "{'a': 1,}"
        yield ' and TOOL CALL: myfunc {"x":1}'
        # Signal end of stream to flush processors
        yield b"data: [DONE]\n\n"

    results: list[StreamingContent] = []
    async for item in normalizer.process_stream(stream(), output_format="objects"):
        if isinstance(item, StreamingContent):
            results.append(item)

    non_empty = [r for r in results if r.content or r.is_done]
    combined_content = "".join(
        _content_to_text(r.content) for r in non_empty if r.content
    )

    # The content should contain the repaired JSON
    assert '{"a": 1}' in combined_content

    # The tool call text should remain in content unchanged
    # (ToolCallRepairProcessor is now a pass-through, no extraction)
    assert "TOOL CALL: myfunc" in combined_content


@pytest.mark.asyncio
async def test_sse_formatting_with_json_repair_bytes() -> None:
    json_proc = JsonRepairProcessor(
        repair_service=JsonRepairService(),
        buffer_cap_bytes=4096,
        strict_mode=False,
    )
    normalizer = StreamNormalizer([json_proc])

    async def stream() -> AsyncGenerator[object, None]:
        yield "Text before: "
        yield "{'msg': 'hi',}"
        yield b"data: [DONE]\n\n"

    chunks: list[bytes] = []
    async for chunk in normalizer.process_stream(stream(), output_format="bytes"):
        if isinstance(chunk, bytes):
            chunks.append(chunk)

    # Ensure SSE frames (data: prefix) are produced
    assert all(c.startswith(b"data: ") for c in chunks)
    # Ensure repaired JSON appears (escaped within SSE JSON string)
    assert any(b'{\\"msg\\": \\"hi\\"}' in c for c in chunks)


@pytest.mark.asyncio
async def test_schema_aware_json_repair_success() -> None:
    # Schema requires object with integer 'a' and string 'b'
    schema = {
        "type": "object",
        "required": ["a", "b"],
        "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
    }

    json_proc = JsonRepairProcessor(
        repair_service=JsonRepairService(),
        buffer_cap_bytes=4096,
        strict_mode=False,
        schema=schema,
    )
    normalizer = StreamNormalizer([json_proc])

    # Malformed JSON that, when repaired, matches the schema
    async def stream() -> AsyncGenerator[object, None]:
        yield "prefix "
        yield "{'a': 1, 'b': 'x',}"
        yield b"data: [DONE]\n\n"

    results: list[StreamingContent] = []
    async for item in normalizer.process_stream(stream(), output_format="objects"):
        if isinstance(item, StreamingContent):
            results.append(item)

    repaired = "".join(
        _content_to_text(chunk.content) for chunk in results if chunk.content
    )
    obj = json.loads(repaired[repaired.find("{") :])
    assert obj == {"a": 1, "b": "x"}


@pytest.mark.asyncio
async def test_schema_aware_json_repair_invalid_yields_raw() -> None:
    # Schema requires integer 'a'; stream provides string 'a', which remains invalid
    schema = {
        "type": "object",
        "required": ["a"],
        "properties": {"a": {"type": "integer"}},
    }

    json_proc = JsonRepairProcessor(
        repair_service=JsonRepairService(),
        buffer_cap_bytes=4096,
        strict_mode=False,
        schema=schema,
    )
    normalizer = StreamNormalizer([json_proc])

    async def stream() -> AsyncGenerator[object, None]:
        # After repair this becomes {"a": "not-int"}, which violates schema
        yield "{'a': 'not-int'}"
        yield b"data: [DONE]\n\n"

    outputs: list[StreamingContent] = []
    async for item in normalizer.process_stream(stream(), output_format="objects"):
        if isinstance(item, StreamingContent):
            outputs.append(item)

    combined = "".join(
        _content_to_text(chunk.content) for chunk in outputs if chunk.content
    )
    # Since validation fails, processor should flush raw buffer (original text)
    assert "{'a': 'not-int'}" in combined


@pytest.mark.asyncio
async def test_large_buffer_exceeds_cap_but_repairs_at_completion() -> None:
    # Small cap to force exceed
    json_proc = JsonRepairProcessor(
        repair_service=JsonRepairService(),
        buffer_cap_bytes=20,
        strict_mode=False,
    )
    normalizer = StreamNormalizer([json_proc])

    part1 = '{"data": "' + "a" * 25 + ', "more": "'
    part2 = "b" * 25 + '"}'

    async def stream() -> AsyncGenerator[object, None]:
        yield part1
        yield part2
        yield b"data: [DONE]\n\n"

    results: list[StreamingContent] = []
    async for item in normalizer.process_stream(stream(), output_format="objects"):
        if isinstance(item, StreamingContent):
            results.append(item)

    combined = "".join(
        _content_to_text(chunk.content) for chunk in results if chunk.content
    )
    obj = json.loads(combined[combined.find("{") :])
    assert obj == {"data": "" + "a" * 25 + "", "more": "" + "b" * 25 + ""}
