"""
Integration tests for tool call buffering in the full streaming pipeline.

These tests verify that tool calls are properly buffered and correlated
across the entire streaming pipeline, from raw chunks to SSE output.

Key scenarios tested:
1. XML tool calls split across chunks with different IDs (Gemini-style)
2. XML leakage prevention in SSE output
3. Full command preservation through the pipeline
4. Session ID correlation for buffering
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestToolCallBufferingIntegration:
    """
    Integration tests for tool call buffering through the FastAPI adapter.
    """

    @pytest.mark.asyncio
    async def test_execute_command_buffered_with_different_chunk_ids(self) -> None:
        """
        CRITICAL INTEGRATION TEST: Tool calls must be buffered correctly
        even when chunks have different 'id' fields.

        This tests the fix for the bug where Gemini-style streaming (different
        IDs per chunk) caused tool calls to be split incorrectly.
        """
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        session_id = "test-session-integration"

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            # Chunk 1: Start of execute_command (with one ID)
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-chunk1", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "I will run tests.\\n<execute_command>\\n<command>./.venv/Scripts"}, "finish_reason": null}]}\n\n',
                metadata={"session_id": session_id},
            )

            # Chunk 2: Completion of execute_command (with DIFFERENT ID)
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-chunk2", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "/python.exe -m pytest</command>\\n</execute_command>"}, "finish_reason": "stop"}]}\n\n',
                metadata={"session_id": session_id},
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        # Collect all output
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        full_output = b"".join(chunks).decode("utf-8")

        # CRITICAL: The full command MUST be present in the output
        assert "./.venv/Scripts/python.exe -m pytest" in full_output, (
            f"Full command not found! Tool call was split incorrectly.\n"
            f"Output:\n{full_output}"
        )

        # Verify complete XML structure
        assert "<execute_command>" in full_output
        assert "</execute_command>" in full_output
        assert "<command>" in full_output
        assert "</command>" in full_output

    @pytest.mark.asyncio
    async def test_ask_followup_question_no_xml_leakage(self) -> None:
        """
        Test that ask_followup_question doesn't leak partial XML.

        This tests the fix for the "What can I help you with today?</" bug.
        """
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        session_id = "test-session-leakage"

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            # Chunk 1: Greeting and start of tool call
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hello! I\'m Kilo Code.\\n<ask_followup_question>\\n<question>What can I help you with today?</"}, "finish_reason": null}]}\n\n',
                metadata={"session_id": session_id},
            )

            # Chunk 2: Completion of tool call
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "question>\\n</ask_followup_question>"}, "finish_reason": "stop"}]}\n\n',
                metadata={"session_id": session_id},
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        full_output = b"".join(chunks).decode("utf-8")

        # Check for incomplete closing tags (the leakage pattern)
        import re

        incomplete_close_pattern = re.compile(r"</[a-z_]+(?![a-z_>])")
        incomplete_matches = incomplete_close_pattern.findall(full_output)

        assert not incomplete_matches, (
            f"XML leakage detected! Incomplete closing tags: {incomplete_matches}\n"
            f"Output:\n{full_output}"
        )

        # Verify complete structure
        assert "<ask_followup_question>" in full_output
        assert "</ask_followup_question>" in full_output

    @pytest.mark.asyncio
    async def test_read_file_buffered_correctly(self) -> None:
        """Test that read_file tool calls are buffered correctly."""
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        session_id = "test-session-read-file"

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Let me read that file.\\n<read_file>\\n<file>src/main"}, "finish_reason": null}]}\n\n',
                metadata={"session_id": session_id},
            )

            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ".py</file>\\n</read_file>"}, "finish_reason": "stop"}]}\n\n',
                metadata={"session_id": session_id},
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        full_output = b"".join(chunks).decode("utf-8")

        # Full file path should be present
        assert (
            "src/main.py" in full_output
        ), f"Full file path not found! Output:\n{full_output}"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_stream(self) -> None:
        """Test that multiple tool calls in a stream are handled correctly."""
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        session_id = "test-session-multi"

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            # First tool call
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "<read_file>\\n<file>src/a.py</file>\\n</read_file>\\n"}, "finish_reason": null}]}\n\n',
                metadata={"session_id": session_id},
            )

            # Second tool call
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "<read_file>\\n<file>src/b.py</file>\\n</read_file>"}, "finish_reason": "stop"}]}\n\n',
                metadata={"session_id": session_id},
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        full_output = b"".join(chunks).decode("utf-8")

        # Both tool calls should be present
        assert "src/a.py" in full_output
        assert "src/b.py" in full_output

    @pytest.mark.asyncio
    async def test_nested_xml_content_preserved(self) -> None:
        """Test that nested XML content (like code) is preserved."""
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        session_id = "test-session-nested"

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "<write_to_file>\\n<file>test.xml</file>\\n<content><root><item>value</item></root></content>\\n</write_to_file>"}, "finish_reason": "stop"}]}\n\n',
                metadata={"session_id": session_id},
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        full_output = b"".join(chunks).decode("utf-8")

        # Nested XML should be preserved
        assert "<root>" in full_output
        assert "</root>" in full_output


class TestStreamIdPropagation:
    """
    Tests for stream_id propagation through the pipeline.
    """

    @pytest.mark.asyncio
    async def test_stream_id_from_metadata_is_used(self) -> None:
        """Test that stream_id from metadata is used for buffering."""
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        stream_id = "explicit-stream-id-123"

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-different", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "<execute_command><command>ls</command>"}, "finish_reason": null}]}\n\n',
                metadata={"stream_id": stream_id},  # Explicit stream_id
            )

            yield ProcessedResponse(
                content='data: {"id": "chatcmpl-also-different", "object": "chat.completion.chunk", "created": 1234567890, "model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "</execute_command>"}, "finish_reason": "stop"}]}\n\n',
                metadata={"stream_id": stream_id},  # Same stream_id
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        full_output = b"".join(chunks).decode("utf-8")

        # Tool call should be complete
        assert "<execute_command>" in full_output
        assert "</execute_command>" in full_output
        assert "<command>ls</command>" in full_output


class TestEdgeCasesIntegration:
    """
    Integration tests for edge cases.
    """

    @pytest.mark.asyncio
    async def test_empty_stream_handled(self) -> None:
        """Test that empty streams are handled gracefully."""
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            # Empty stream - just yield nothing
            return
            yield  # Make it a generator

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Should not raise any errors
        assert True

    @pytest.mark.asyncio
    async def test_done_marker_emitted(self) -> None:
        """Test that [DONE] marker is emitted at end of stream."""
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content='data: {"id": "test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": "stop"}]}\n\n',
                metadata={"session_id": "test"},
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        full_output = b"".join(chunks).decode("utf-8")

        # [DONE] marker should be present
        assert "[DONE]" in full_output

    @pytest.mark.asyncio
    async def test_very_long_command_preserved(self) -> None:
        """Test that very long commands are preserved completely."""
        from src.core.transport.fastapi.response_adapters import (
            to_fastapi_streaming_response,
        )

        # A very long command
        long_command = "./.venv/Scripts/python.exe -m pytest " + " ".join(
            [f"tests/unit/test_file_{i}.py::test_function_{i}" for i in range(50)]
        )

        session_id = "test-session-long"

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            # Split the long command across multiple chunks
            content = f"<execute_command>\\n<command>{long_command}</command>\\n</execute_command>"

            # Emit in chunks of ~100 chars
            chunk_size = 100
            for i in range(0, len(content), chunk_size):
                chunk_content = content[i : i + chunk_size]
                is_last = i + chunk_size >= len(content)
                finish_reason = '"stop"' if is_last else "null"
                yield ProcessedResponse(
                    content=f'data: {{"id": "test", "object": "chat.completion.chunk", "created": 1234567890, "model": "test", "choices": [{{"index": 0, "delta": {{"content": "{chunk_content}"}}, "finish_reason": {finish_reason}}}]}}\n\n',
                    metadata={"session_id": session_id},
                )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
        )

        response = to_fastapi_streaming_response(envelope)

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        full_output = b"".join(chunks).decode("utf-8")

        # The full command should be present
        assert "./.venv/Scripts/python.exe -m pytest" in full_output
        # Check for some of the test files
        assert "test_file_0.py" in full_output
        assert "test_file_49.py" in full_output
