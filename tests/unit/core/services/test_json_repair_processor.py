from __future__ import annotations

import json
from typing import Any

import pytest
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.streaming.json_repair_processor import JsonRepairProcessor


def _content_to_text(content: str | dict[str, Any] | bytes | None) -> str:
    if isinstance(content, bytes):
        return content.decode("utf-8", "ignore")
    if isinstance(content, dict):
        return json.dumps(content, sort_keys=True)
    return content or ""


@pytest.fixture()
def processor() -> JsonRepairProcessor:
    return JsonRepairProcessor(
        repair_service=JsonRepairService(),
        buffer_cap_bytes=1024,
        strict_mode=False,
    )


async def _run_processor_chunks(processor: JsonRepairProcessor, *chunks: str) -> str:
    out: list[str] = []
    stream_metadata = {"stream_id": "test-stream"}
    for ch in chunks:
        res = await processor.process(
            StreamingContent(content=ch, metadata=dict(stream_metadata))
        )
        if res.content:
            out.append(_content_to_text(res.content))
    # flush end
    res = await processor.process(
        StreamingContent(content="", is_done=True, metadata=dict(stream_metadata))
    )
    if res.content:
        out.append(_content_to_text(res.content))
    return "".join(out)


@pytest.mark.asyncio
async def test_stream_with_valid_json_passes_through(
    processor: JsonRepairProcessor,
) -> None:
    result = await _run_processor_chunks(processor, '{"a": 1}')
    assert json.loads(result) == {"a": 1}


@pytest.mark.asyncio
async def test_stream_with_reparable_json_is_repaired(
    processor: JsonRepairProcessor,
) -> None:
    result = await _run_processor_chunks(processor, "{'a': 1,}")
    assert json.loads(result) == {"a": 1}


@pytest.mark.asyncio
async def test_stream_with_text_before_json(processor: JsonRepairProcessor) -> None:
    result = await _run_processor_chunks(processor, "Some text before ", '{"a": 1}')
    assert result.startswith("Some text before ")
    assert json.loads(result[len("Some text before ") :]) == {"a": 1}


@pytest.mark.asyncio
async def test_stream_with_text_after_json(processor: JsonRepairProcessor) -> None:
    result = await _run_processor_chunks(processor, '{"a": 1}', " and some text after")
    repaired_part = result.replace(" and some text after", "")
    assert json.loads(repaired_part) == {"a": 1}
    assert result.endswith(" and some text after")


@pytest.mark.asyncio
async def test_stream_with_fragmented_json(processor: JsonRepairProcessor) -> None:
    result = await _run_processor_chunks(processor, '{"a":', " 1,", '"b": "two"}')
    assert json.loads(result) == {"a": 1, "b": "two"}


@pytest.mark.asyncio
async def test_non_json_stream_passes_through(processor: JsonRepairProcessor) -> None:
    result = await _run_processor_chunks(processor, "Hello, ", "world!")
    assert result == "Hello, world!"


@pytest.mark.asyncio
async def test_multiple_json_objects_in_stream(processor: JsonRepairProcessor) -> None:
    result = await _run_processor_chunks(processor, '{"a": 1} some text {"b": 2}')
    assert '{"a": 1}' in result
    assert '{"b": 2}' in result


@pytest.mark.asyncio
async def test_json_with_escaped_quotes_is_repaired(
    processor: JsonRepairProcessor,
) -> None:
    result = await _run_processor_chunks(processor, '{"message": "Hello "world"!"}')
    assert json.loads(result) == {"message": 'Hello "world"!'}


@pytest.mark.asyncio
async def test_json_with_trailing_backslash_is_emitted(
    processor: JsonRepairProcessor,
) -> None:
    json_input = json.dumps({"path": "abc\\"})
    result = await _run_processor_chunks(processor, json_input)
    assert result
    assert json.loads(result) == {"path": "abc\\"}


@pytest.mark.asyncio
async def test_large_json_exceeding_buffer_is_repaired() -> None:
    processor = JsonRepairProcessor(
        repair_service=JsonRepairService(),
        buffer_cap_bytes=20,
        strict_mode=False,
    )
    long_json_part1 = '{"data": "' + "a" * 10 + ', "more": "'
    long_json_part2 = "b" * 10 + '"}'
    result = await _run_processor_chunks(processor, long_json_part1, long_json_part2)
    expected_json = json.loads(
        '{"data": "' + "a" * 10 + '", "more": "' + "b" * 10 + '"}'
    )
    assert json.loads(result) == expected_json


@pytest.mark.asyncio
async def test_stream_with_non_json_then_json_then_non_json(
    processor: JsonRepairProcessor,
) -> None:
    result = await _run_processor_chunks(processor, "START: ", '{"a": 1}', " END")
    assert result == 'START: {"a": 1} END'


@pytest.mark.asyncio
async def test_stream_ending_with_incomplete_json_is_flushed_and_repaired(
    processor: JsonRepairProcessor,
) -> None:
    result = await _run_processor_chunks(processor, '{"key": "value", "incomplete":')
    assert json.loads(result) == {"key": "value", "incomplete": None}


@pytest.mark.asyncio
async def test_stream_with_multiple_reparable_json_objects(
    processor: JsonRepairProcessor,
) -> None:
    result = await _run_processor_chunks(
        processor, "Text1 {'a': 1,} Text2 {'b': 2,} Text3"
    )
    assert result == 'Text1 {"a": 1} Text2 {"b": 2} Text3'


@pytest.mark.asyncio
async def test_xml_tool_payload_is_not_modified(
    processor: JsonRepairProcessor,
) -> None:
    apply_diff_payload = """<apply_diff>
<args>
<file>
  <path>scripts/demo.py</path>
  <diff>
    <content><![CDATA[
<<<<<<< SEARCH
foo = "bar"
=======
foo = "baz"
>>>>>>> REPLACE
]]></content>
  </diff>
</file>
</args>
</apply_diff>"""

    result = await _run_processor_chunks(processor, apply_diff_payload)

    assert result == apply_diff_payload
    assert "<![CDATA[" in result
    assert '<!["' not in result


@pytest.mark.asyncio
async def test_checklist_brackets_are_preserved(
    processor: JsonRepairProcessor,
) -> None:
    todo_payload = """<update_todo_list>
<todos>
[-] first task
[ ] second task
[x] done task
</todos>
</update_todo_list>"""

    result = await _run_processor_chunks(processor, todo_payload)

    assert "[-] first task" in result
    assert "[ ] second task" in result
    assert "[x] done task" in result


@pytest.mark.asyncio
async def test_buffered_chunks_preserve_metadata_and_usage(
    processor: JsonRepairProcessor,
) -> None:
    chunk = StreamingContent(
        content='{"partial": ',
        metadata={"id": "chunk-123"},
        usage={"prompt_tokens": 4},
        raw_data={"raw": "data"},
    )

    result = await processor.process(chunk)

    assert result.content == ""
    assert result.metadata == {"id": "chunk-123"}
    assert result.usage == {"prompt_tokens": 4}
    assert result.raw_data == {"raw": "data"}
    assert not result.is_done
    assert not result.is_cancellation
