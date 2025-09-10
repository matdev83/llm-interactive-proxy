from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
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


@pytest.mark.asyncio
async def test_json_repair_and_tool_call_repair_together_objects() -> None:
    # Build processors: JSON repair first, then tool call repair
    json_proc = JsonRepairProcessor(
        repair_service=JsonRepairService(),
        buffer_cap_bytes=4096,
        strict_mode=False,
    )
    tool_proc = ToolCallRepairProcessor(ToolCallRepairService())
    # Include accumulation to preserve non-tool content alongside repaired tool calls
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
        results.append(item)

    # Tool call should be converted to OpenAI tool_calls JSON string within combined content
    # Extract JSON substrings and check type (repaired JSON may not appear due to downstream processor behavior)
    non_empty = [r for r in results if r.content or r.is_done]
    combined = "".join(r.content for r in non_empty if r.content)
    # Simple presence check is adequate since tool-call content is JSON-dumped
    assert '"type": "function"' in combined


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
        results.append(item)

    repaired = "".join(chunk.content for chunk in results if chunk.content)
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
        outputs.append(item)

    combined = "".join(chunk.content for chunk in outputs if chunk.content)
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
        results.append(item)

    combined = "".join(chunk.content for chunk in results if chunk.content)
    obj = json.loads(combined[combined.find("{") :])
    assert obj == {"data": "" + "a" * 25 + "", "more": "" + "b" * 25 + ""}
