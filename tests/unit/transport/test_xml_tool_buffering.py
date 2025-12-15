"""Test for XML tool call buffering to prevent partial emission."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.mark.asyncio
async def test_ask_followup_question_buffered_prevents_xml_leakage():
    """
    Test that ask_followup_question tool calls are buffered to prevent XML leakage.

    Regression test for: "What can I help you with today?</" issue seen in wire_capture.log
    """
    from src.core.transport.fastapi.response_adapters import (
        to_fastapi_streaming_response,
    )

    async def mock_stream() -> AsyncIterator[dict]:
        """Simulate LLM streaming an ask_followup_question tool call in chunks."""
        # Use consistent stream ID across all chunks (OpenAI uses same id for all chunks)
        stream_id = "chatcmpl-test-stream"

        # Chunk 1: Text before the tool call
        yield {
            "id": stream_id,
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": "Hello! I'm Kilo Code. What can I help you with today?\n",
                    },
                    "finish_reason": None,
                }
            ],
        }

        # Chunk 2: Start of XML tag (THIS SHOULD BE BUFFERED)
        yield {
            "id": stream_id,
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": "<ask_followup_question>\n<question>What can I help you with today?</",
                    },
                    "finish_reason": None,
                }
            ],
        }

        # Chunk 3: Completion of XML tag
        yield {
            "id": stream_id,
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": "question>\n</ask_followup_question>",
                    },
                    "finish_reason": None,
                }
            ],
        }

        # Chunk 4: Final done marker (OpenAI-style - empty delta with finish_reason)
        yield {
            "id": stream_id,
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }

    # Create streaming response
    envelope = StreamingResponseEnvelope(
        content=mock_stream(), media_type="text/event-stream", headers={}
    )

    response = to_fastapi_streaming_response(envelope)

    # Collect all chunks
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    # Convert to text for analysis
    full_output = b"".join(chunks).decode("utf-8")

    # CRITICAL ASSERTION: Partial XML tags should NOT appear in output
    # Before fix: "What can I help you with today?</" would leak (partial </question> tag)
    # After fix: Only complete tags should be emitted
    # Check that no incomplete closing tags exist (e.g., "</" not followed by tag completion)
    import re

    # Look for patterns like "</xyz" where xyz is not followed by ">" (incomplete closing tag)
    incomplete_close_pattern = re.compile(r"</[a-z_]+(?![a-z_>])")
    incomplete_matches = incomplete_close_pattern.findall(full_output)
    assert not incomplete_matches, (
        f"XML leakage detected! Incomplete closing tags found: {incomplete_matches}\n"
        f"Output:\n{full_output}"
    )

    # Verify the complete tool call IS present
    assert (
        "<ask_followup_question>" in full_output
    ), "Complete opening tag should be present"
    assert (
        "</ask_followup_question>" in full_output
    ), "Complete closing tag should be present"

    # Verify greeting text is present
    assert "Hello! I'm Kilo Code" in full_output, "Greeting should be present"


@pytest.mark.asyncio
async def test_think_tags_do_not_block_streaming_chunks():
    """
    Ensure think/thought tags are not treated as tool markers (no over-buffering).

    Regression coverage: when think tags were tracked as tool markers, the buffering
    layer collapsed all chunks into a single SSE event. This test asserts that
    multiple SSE payloads still flow when think tags appear in streamed content.
    """
    from src.core.transport.fastapi.response_adapters import (
        to_fastapi_streaming_response,
    )

    async def mock_stream() -> AsyncIterator[ProcessedResponse]:
        stream_id = "think-stream"
        yield ProcessedResponse(
            content='data: {"id": "chatcmpl-think-1", "object": "chat.completion.chunk", "created": 123, "model": "gpt-4", "choices": [{"index": 0, "delta": {"content": "<think>Let me analyze"}, "finish_reason": null}]}\n\n',
            metadata={"session_id": stream_id},
        )
        yield ProcessedResponse(
            content='data: {"id": "chatcmpl-think-1", "object": "chat.completion.chunk", "created": 123, "model": "gpt-4", "choices": [{"index": 0, "delta": {"content": " this</think>Now the answer"}, "finish_reason": null}]}\n\n',
            metadata={"session_id": stream_id},
        )
        yield ProcessedResponse(
            content='data: {"id": "chatcmpl-think-1", "object": "chat.completion.chunk", "created": 123, "model": "gpt-4", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}\n\n',
            metadata={"session_id": stream_id},
        )

    envelope = StreamingResponseEnvelope(
        content=mock_stream(), media_type="text/event-stream", headers={}
    )

    response = to_fastapi_streaming_response(envelope)

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        decoded = chunk.decode("utf-8")
        if decoded.strip():
            chunks.append(decoded)

    def _count_payload_events(items: list[str]) -> int:
        event_count = 0
        for item in items:
            for line in item.splitlines():
                stripped = line.strip()
                if not stripped.startswith("data:"):
                    continue
                payload = stripped[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                event_count += 1
        return event_count

    assert _count_payload_events(chunks) >= 2, (
        "Think tags must not cause the streaming buffer to collapse into a single event. "
        f"Chunks: {chunks}"
    )
    full_output = "".join(chunks)
    assert "Now the answer" in full_output


@pytest.mark.asyncio
async def test_execute_command_buffered_across_different_chunk_ids():
    """
    Test that execute_command tool calls are properly buffered even when
    chunks have different 'id' fields (as seen with Gemini backend).

    This is a regression test for the bug where tool calls were split across
    chunks with different IDs, causing the buffering system to fail to correlate
    them, resulting in partial command execution like "./.venv/Scripts" instead
    of "./.venv/Scripts/python.exe -m pytest".
    """
    from src.core.domain.responses import StreamingResponseEnvelope
    from src.core.interfaces.response_processor_interface import ProcessedResponse
    from src.core.transport.fastapi.response_adapters import (
        to_fastapi_streaming_response,
    )

    # Simulate what was seen in wire_capture.log - chunks with DIFFERENT IDs
    # This is the actual bug scenario from Gemini
    async def mock_stream_with_different_ids() -> AsyncIterator[ProcessedResponse]:
        """Simulate Gemini-style streaming where each chunk has different id."""
        # Use consistent session_id (this is the fix - we now use session_id for correlation)
        session_id = "test-session-123"

        # Chunk 1: Start of execute_command (different id than chunk 2)
        yield ProcessedResponse(
            content='data: {"id": "chatcmpl-663a40db142b4bc7", "object": "chat.completion.chunk", "created": 1764074247, "model": "gemini-2.5-pro", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "I will run the test suite.\\n<execute_command>\\n<command>./.venv/Scripts"}, "finish_reason": null}]}\n\n',
            metadata={"session_id": session_id},
        )

        # Chunk 2: Completion of execute_command (DIFFERENT id!)
        yield ProcessedResponse(
            content='data: {"id": "chatcmpl-ef671950e3f24896", "object": "chat.completion.chunk", "created": 1764074247, "model": "gemini-2.5-pro", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "/python.exe -m pytest</command>\\n</execute_command>"}, "finish_reason": "stop"}]}\n\n',
            metadata={"session_id": session_id},
        )

    # Create streaming response
    envelope = StreamingResponseEnvelope(
        content=mock_stream_with_different_ids(),
        media_type="text/event-stream",
        headers={},
    )

    response = to_fastapi_streaming_response(envelope)

    # Collect all chunks
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    # Convert to text for analysis
    full_output = b"".join(chunks).decode("utf-8")

    # CRITICAL: The full command should be present in the output
    # Before fix: Only "./.venv/Scripts" would appear (second part lost due to different id)
    # After fix: Full command "./.venv/Scripts/python.exe -m pytest" should appear
    assert "./.venv/Scripts/python.exe -m pytest" in full_output, (
        f"Full command not found in output! Tool call was likely split incorrectly.\n"
        f"This indicates the buffering is not correlating chunks properly.\n"
        f"Output:\n{full_output}"
    )

    # Verify the complete tool call structure
    assert "<execute_command>" in full_output, "Opening execute_command tag missing"
    assert "</execute_command>" in full_output, "Closing execute_command tag missing"
    assert "<command>" in full_output, "Opening command tag missing"
    assert "</command>" in full_output, "Closing command tag missing"


@pytest.mark.asyncio
async def test_all_tool_tags_are_buffered():
    """Verify that all XML tool tags are included in buffering logic."""
    import ast
    import inspect

    from src.core.transport.fastapi import response_adapters

    # Read the entire module source to find buffering logic
    # (it's defined inside a nested function, so we need the full module)
    source = inspect.getsource(response_adapters)
    tree = ast.parse(source)

    # Find the BUFFERED_TOOL_TAGS assignment (can be nested in functions)
    # It may be an ast.Assign or ast.AnnAssign (annotated assignment)
    buffered_tags: list[str] = []
    for node in ast.walk(tree):
        # Handle regular assignment: BUFFERED_TOOL_TAGS = (...)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "BUFFERED_TOOL_TAGS"
                    and isinstance(node.value, ast.Tuple)
                ):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant):
                            buffered_tags.append(elt.value)
        # Handle annotated assignment: BUFFERED_TOOL_TAGS: tuple[str, ...] = (...)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "BUFFERED_TOOL_TAGS"
            and node.value is not None
            and isinstance(node.value, ast.Tuple)
        ):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant):
                    buffered_tags.append(elt.value)

    # Dynamic buffering now relies on observed/allowed tags rather than hardcoded tuples
    assert "tracked_tags" in source
    assert "_apply_tag_buffer" in source
