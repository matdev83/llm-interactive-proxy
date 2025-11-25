"""Test for XML tool call buffering to prevent partial emission."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from src.core.domain.responses import StreamingResponseEnvelope


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
async def test_all_tool_tags_are_buffered():
    """Verify that all XML tool tags are included in buffering logic."""
    import ast
    import inspect

    from src.core.transport.fastapi import response_adapters

    # These are the tool tags that MUST be buffered based on the system prompt
    critical_tool_tags = [
        "ask_followup_question",  # This was causing the leakage!
        "attempt_completion",
        "execute_command",
        "apply_diff",
        "write_to_file",
        "read_file",
        "use_mcp_tool",
        "access_mcp_resource",
        "browser_action",
    ]

    # Read the entire module source to find BUFFERED_TOOL_TAGS
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

    # Verify all critical tags are buffered
    for tag in critical_tool_tags:
        assert tag in buffered_tags, (
            f"Tool tag '{tag}' MUST be in BUFFERED_TOOL_TAGS to prevent XML leakage! "
            f"Current buffered tags: {buffered_tags}"
        )
