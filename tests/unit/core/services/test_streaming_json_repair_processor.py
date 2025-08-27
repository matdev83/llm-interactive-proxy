from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import pytest
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.streaming_json_repair_processor import (
    StreamingJsonRepairProcessor,
)


@pytest.fixture
def json_repair_service() -> JsonRepairService:
    return JsonRepairService()


@pytest.fixture
def processor(json_repair_service: JsonRepairService) -> StreamingJsonRepairProcessor:
    return StreamingJsonRepairProcessor(
        repair_service=json_repair_service, buffer_cap_bytes=1024, strict_mode=False
    )


async def _collect_stream(stream: AsyncGenerator[str, None]) -> str:
    return "".join([item async for item in stream])


@pytest.mark.asyncio
async def test_stream_with_valid_json_passes_through(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield '{"a": 1}'

    result = await _collect_stream(processor.process_stream(stream()))
    assert json.loads(result) == {"a": 1}


@pytest.mark.asyncio
async def test_stream_with_reparable_json_is_repaired(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield "{'a': 1,}"

    result = await _collect_stream(processor.process_stream(stream()))
    assert json.loads(result) == {"a": 1}


@pytest.mark.asyncio
async def test_stream_with_text_before_json(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield "Some text before "
        yield '{"a": 1}'

    result = await _collect_stream(processor.process_stream(stream()))
    assert result.startswith("Some text before ")
    assert json.loads(result[len("Some text before ") :]) == {"a": 1}


@pytest.mark.asyncio
async def test_stream_with_text_after_json(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield '{"a": 1}'
        yield " and some text after"

    # In the new implementation, text after a completed JSON object is flushed.
    result = await _collect_stream(processor.process_stream(stream()))
    repaired_part = result.replace(" and some text after", "")
    assert json.loads(repaired_part) == {"a": 1}
    assert result.endswith(" and some text after")


@pytest.mark.asyncio
async def test_stream_with_fragmented_json(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield '{"a":'
        yield " 1,"
        yield '"b": "two"}'

    result = await _collect_stream(processor.process_stream(stream()))
    assert json.loads(result) == {"a": 1, "b": "two"}


@pytest.mark.asyncio
async def test_buffer_cap_is_respected(
    json_repair_service: JsonRepairService,
) -> None:
    processor = StreamingJsonRepairProcessor(
        repair_service=json_repair_service, buffer_cap_bytes=5, strict_mode=False
    )

    async def stream() -> AsyncGenerator[str, None]:
        yield '{"a": 1, "b": 2, "c": 3}'

    # The buffer will overflow and flush the raw (unrepaired) content
    result = await _collect_stream(processor.process_stream(stream()))
    assert result == '{"a": 1, "b": 2, "c": 3}'


@pytest.mark.asyncio
async def test_non_json_stream_passes_through(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield "Hello, "
        yield "world!"

    result = await _collect_stream(processor.process_stream(stream()))
    assert result == "Hello, world!"


@pytest.mark.asyncio
async def test_multiple_json_objects_in_stream(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield '{"a": 1} some text {"b": 2}'

    result = await _collect_stream(processor.process_stream(stream()))
    # The processor should handle them sequentially, passing text through.
    assert '{"a": 1}' in result
    assert '{"b": 2}' in result


@pytest.mark.asyncio
async def test_json_with_escaped_quotes_is_repaired(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield '{"message": "Hello "world"!"}'

    result = await _collect_stream(processor.process_stream(stream()))
    assert json.loads(result) == {"message": 'Hello "world"!'}


@pytest.mark.asyncio
async def test_large_json_exceeding_buffer_is_repaired(
    json_repair_service: JsonRepairService,
) -> None:
    # Set a small buffer cap to force overflow
    processor = StreamingJsonRepairProcessor(
        repair_service=json_repair_service, buffer_cap_bytes=20, strict_mode=False
    )

    long_json_part1 = '{"data": "' + "a" * 10 + ', "more": "'
    long_json_part2 = "b" * 10 + '"}'

    async def stream() -> AsyncGenerator[str, None]:
        yield long_json_part1
        yield long_json_part2

    result = await _collect_stream(processor.process_stream(stream()))
    # The processor should still attempt to repair the full JSON after buffering
    # Build the valid expected JSON explicitly (the input was intentionally malformed: missing closing quote)
    expected_json = json.loads(
        '{"data": "' + "a" * 10 + '", "more": "' + "b" * 10 + '"}'
    )
    assert json.loads(result) == expected_json


@pytest.mark.asyncio
async def test_stream_with_non_json_then_json_then_non_json(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield "START: "
        yield '{"a": 1}'
        yield " END"

    result = await _collect_stream(processor.process_stream(stream()))
    assert result == 'START: {"a": 1} END'


@pytest.mark.asyncio
async def test_stream_ending_with_incomplete_json_is_flushed_and_repaired(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield '{"key": "value", "incomplete":'

    result = await _collect_stream(processor.process_stream(stream()))
    # The repair service should attempt to fix the incomplete JSON
    assert json.loads(result) == {"key": "value", "incomplete": None}


@pytest.mark.asyncio
async def test_stream_with_multiple_reparable_json_objects(
    processor: StreamingJsonRepairProcessor,
) -> None:
    async def stream() -> AsyncGenerator[str, None]:
        yield "Text1 {'a': 1,} Text2 {'b': 2,} Text3"

    result = await _collect_stream(processor.process_stream(stream()))
    # Expecting repaired JSON objects and original text to be interleaved
    assert result == 'Text1 {"a": 1} Text2 {"b": 2} Text3'
