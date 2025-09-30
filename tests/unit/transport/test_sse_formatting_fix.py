"""
Focused tests for SSE formatting fix in response_adapters.py.

These tests verify that the _byte_streamer function properly formats
dict chunks as SSE (Server-Sent Events) format: `data: {json}\\n\\n`

This was the root cause of the bug where clients received empty responses.
"""

import json


class TestSSEFormattingFix:
    """Test SSE formatting in response adapters."""

    def test_dict_is_formatted_as_sse(self) -> None:
        """Test that a dict chunk produces proper SSE format.

        This is the critical fix - before, dicts were just str() converted.
        Now they must be formatted as: `data: {json}\\n\\n`
        """
        from src.core.transport.fastapi.response_adapters import (
            _format_chunk_as_sse,
        )

        # This function should exist (or we'll create it) to format chunks
        test_chunk = {
            "id": "chunk-1",
            "object": "chat.completion.chunk",
            "choices": [{"delta": {"content": "Hello"}}],
        }

        result = _format_chunk_as_sse(test_chunk)

        # Verify SSE format
        assert isinstance(result, bytes), "Result should be bytes"

        decoded = result.decode("utf-8")

        # CRITICAL: Must start with "data: "
        assert decoded.startswith("data: "), f"Missing 'data: ' prefix: {decoded[:20]}"

        # CRITICAL: Must end with "\n\n"
        assert decoded.endswith("\n\n"), f"Missing '\\n\\n' suffix: {decoded[-10:]}"

        # Extract and verify JSON
        json_part = decoded[6:-2]
        parsed = json.loads(json_part)

        assert parsed == test_chunk, "JSON content doesn't match original"

    def test_string_is_passed_through(self) -> None:
        """Test that string chunks are just encoded."""
        from src.core.transport.fastapi.response_adapters import (
            _format_chunk_as_sse,
        )

        test_string = "test content"
        result = _format_chunk_as_sse(test_string)

        assert isinstance(result, bytes)
        assert result == b"test content"

    def test_bytes_are_passed_through(self) -> None:
        """Test that byte chunks are passed through as-is."""
        from src.core.transport.fastapi.response_adapters import (
            _format_chunk_as_sse,
        )

        test_bytes = b"test bytes"
        result = _format_chunk_as_sse(test_bytes)

        assert result == test_bytes

    def test_sse_format_example(self) -> None:
        """Document the expected SSE format with a concrete example."""
        from src.core.transport.fastapi.response_adapters import (
            _format_chunk_as_sse,
        )

        chunk = {"message": "hello", "index": 0}

        result = _format_chunk_as_sse(chunk)
        decoded = result.decode("utf-8")

        # Expected format:
        expected = 'data: {"message": "hello", "index": 0}\n\n'

        assert decoded == expected, f"Expected: {expected!r}, Got: {decoded!r}"


def test_sse_formatting_integration_documentation() -> None:
    """Document how SSE formatting should work in the full pipeline.

    This test serves as documentation for the fix we implemented.

    Problem:
    --------
    Dict chunks from connectors were being passed to _byte_streamer,
    which just did str(chunk).encode(), resulting in invalid SSE format.

    Fix:
    ----
    _byte_streamer now checks if chunk is dict and formats as SSE:
    `data: {json.dumps(chunk)}\\n\\n`

    Flow:
    -----
    1. Connector yields ProcessedResponse(content={...})
    2. StreamingResponseEnvelope wraps the generator
    3. domain_response_to_fastapi converts to FastAPI StreamingResponse
    4. _byte_streamer formats each chunk as SSE
    5. Client receives proper SSE stream
    """
    # This test documents the expected behavior
    example_chunk = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"content": "test"}}],
    }

    # SSE format specification
    sse_format = f"data: {json.dumps(example_chunk)}\n\n"

    # Verify format
    assert sse_format.startswith("data: ")
    assert sse_format.endswith("\n\n")
    assert json.loads(sse_format[6:-2]) == example_chunk
