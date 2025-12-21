"""
Integration tests for VTCResponseStreamWrapper with gemini_base-style streams.

These tests verify that the VTC response wrapper correctly processes
ProcessedResponse streams similar to those produced by gemini_base connector.
"""

from __future__ import annotations

from typing import Any

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.streaming.vtc_response_wrapper import (
    VTCResponseStreamWrapper,
    VTCWrapperConfig,
    wrap_processed_response_stream_with_vtc,
)


def create_gemini_style_chunk(
    content_text: str | None = None,
    finish_reason: str | None = None,
    model: str = "claude-sonnet-4-5",
    chunk_id: str = "chatcmpl-gemini-test",
    tool_calls: list[dict[str, Any]] | None = None,
) -> ProcessedResponse:
    """Create a ProcessedResponse that mimics gemini_base output format."""
    delta: dict[str, Any] = {}
    if content_text is not None:
        delta["content"] = content_text
    if tool_calls:
        delta["tool_calls"] = tool_calls

    choice: dict[str, Any] = {"index": 0, "delta": delta}
    if finish_reason:
        choice["finish_reason"] = finish_reason

    return ProcessedResponse(
        content={
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": model,
            "choices": [choice],
        },
        metadata={
            "id": chunk_id,
            "model": model,
            "created": 1234567890,
        },
    )


def extract_all_text(chunks: list[ProcessedResponse]) -> str:
    """Extract and concatenate all text content from chunks."""
    texts = []
    for chunk in chunks:
        content = chunk.content
        if not isinstance(content, dict):
            continue
        choices = content.get("choices", [])
        if not choices:
            continue
        delta = choices[0].get("delta", {})
        text = delta.get("content", "")
        if text:
            texts.append(text)
    return "".join(texts)


class TestVTCResponseWrapperGeminiIntegration:
    """Integration tests with gemini_base-style ProcessedResponse streams."""

    @pytest.mark.asyncio
    async def test_realistic_gemini_stream_with_tool_call(self):
        """
        Test processing a realistic gemini_base stream with a tool call.

        This simulates what KiloCode would see when using antigravity-oauth
        backend with VTC enabled.
        """
        # Simulate a typical gemini_base response with tool call
        chunks = [
            create_gemini_style_chunk("I'll check the "),
            create_gemini_style_chunk("file for you."),
            create_gemini_style_chunk("\n\n<function_calls>\n"),
            create_gemini_style_chunk('<invoke name="read_file">\n'),
            create_gemini_style_chunk(
                '<parameter name="path">/tmp/test.txt</parameter>\n'
            ),
            create_gemini_style_chunk("</invoke>\n"),
            create_gemini_style_chunk("</function_calls>"),
            create_gemini_style_chunk(finish_reason="stop"),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Extract all text
        all_text = extract_all_text(result_chunks)

        # Should contain the intro text
        assert "I'll check the file for you." in all_text or "check the" in all_text

        # Should contain the tool call (re-serialized)
        assert "read_file" in all_text
        assert "path" in all_text

    @pytest.mark.asyncio
    async def test_stream_with_multiple_tool_calls(self):
        """Test stream with multiple tool calls in sequence."""
        # Multiple tool calls in a single response
        xml_content = (
            "<function_calls>\n"
            '<invoke name="list_dir">\n'
            '<parameter name="path">/tmp</parameter>\n'
            "</invoke>\n"
            '<invoke name="read_file">\n'
            '<parameter name="path">/tmp/readme.txt</parameter>\n'
            "</invoke>\n"
            "</function_calls>"
        )

        chunks = [
            create_gemini_style_chunk("Let me explore the directory.\n\n"),
            create_gemini_style_chunk(xml_content),
            create_gemini_style_chunk(finish_reason="tool_calls"),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        all_text = extract_all_text(result_chunks)

        # Both tool calls should be present
        assert "list_dir" in all_text
        assert "read_file" in all_text

    @pytest.mark.asyncio
    async def test_stream_vtc_disabled_passes_through(self):
        """Verify VTC disabled passes through unchanged."""
        original_chunks = [
            create_gemini_style_chunk("Hello world"),
            create_gemini_style_chunk(
                "<function_calls><invoke>test</invoke></function_calls>"
            ),
            create_gemini_style_chunk(finish_reason="stop"),
        ]

        async def mock_stream():
            for chunk in original_chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=False
        ):
            result_chunks.append(chunk)

        # Should have same number of chunks
        assert len(result_chunks) == len(original_chunks)

        # Content should be unchanged
        for orig, result in zip(original_chunks, result_chunks, strict=False):
            assert orig.content == result.content

    @pytest.mark.asyncio
    async def test_tool_call_with_json_parameters(self):
        """Test tool call with complex JSON parameters."""
        xml_content = (
            "<function_calls>\n"
            '<invoke name="todo_write">\n'
            '<parameter name="todos">[{"id": "1", "content": "Task 1"}, '
            '{"id": "2", "content": "Task 2"}]</parameter>\n'
            "</invoke>\n"
            "</function_calls>"
        )

        chunks = [
            create_gemini_style_chunk("I'll create the tasks.\n\n"),
            create_gemini_style_chunk(xml_content),
            create_gemini_style_chunk(finish_reason="tool_calls"),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        all_text = extract_all_text(result_chunks)

        # Tool call should be present
        assert "todo_write" in all_text
        assert "Task 1" in all_text or "Task" in all_text

    @pytest.mark.asyncio
    async def test_chunked_xml_reassembly(self):
        """Test that XML split across many chunks is properly reassembled."""
        # Split XML into very small chunks to stress test buffering
        chunks = [
            create_gemini_style_chunk("<func"),
            create_gemini_style_chunk("tion_calls>"),
            create_gemini_style_chunk("\n<inv"),
            create_gemini_style_chunk("oke "),
            create_gemini_style_chunk('name="ex'),
            create_gemini_style_chunk('ecute_command"'),
            create_gemini_style_chunk(">\n<param"),
            create_gemini_style_chunk('eter name="comm'),
            create_gemini_style_chunk('and">ls -la</'),
            create_gemini_style_chunk("parameter>\n"),
            create_gemini_style_chunk("</invoke>\n"),
            create_gemini_style_chunk("</function_calls>"),
            create_gemini_style_chunk(finish_reason="stop"),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        all_text = extract_all_text(result_chunks)

        # Tool call should have been properly extracted and re-serialized
        assert "execute_command" in all_text
        assert "command" in all_text

    @pytest.mark.asyncio
    async def test_error_chunk_passes_through(self):
        """Error chunks should pass through without modification."""
        error_chunk = ProcessedResponse(
            content={
                "id": "chatcmpl-error",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                "error": {
                    "message": "Rate limit exceeded",
                    "type": "rate_limit_error",
                    "code": 429,
                },
            },
            metadata={"finish_reason": "error"},
        )

        async def mock_stream():
            yield error_chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Error chunk should pass through
        assert len(result_chunks) == 1
        assert result_chunks[0].content.get("error") is not None

    @pytest.mark.asyncio
    async def test_preserve_chunk_metadata(self):
        """Verify that chunk metadata is preserved through processing."""
        chunk = create_gemini_style_chunk(
            content_text="Hello",
            model="claude-sonnet-4-5",
            chunk_id="chatcmpl-preserve-test",
        )
        chunk.metadata["custom_field"] = "custom_value"

        async def mock_stream():
            yield chunk
            yield create_gemini_style_chunk(finish_reason="stop")

        result_chunks = []
        async for c in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(c)

        # Find chunk with content
        content_chunk = next((c for c in result_chunks if extract_all_text([c])), None)
        assert content_chunk is not None

        # Model info should be preserved in content
        assert content_chunk.content.get("model") == "claude-sonnet-4-5"


class TestVTCResponseWrapperEndToEnd:
    """End-to-end tests simulating full agent interaction."""

    @pytest.mark.asyncio
    async def test_kilocode_style_interaction(self):
        """
        Simulate a KiloCode-style agent interaction.

        KiloCode sends XML tool calls in message content and expects
        them back in the same format.
        """
        # Simulate response to "check uncommitted changes"
        chunks = [
            create_gemini_style_chunk("I'll check the local "),
            create_gemini_style_chunk("uncommitted changes.\n\n"),
            create_gemini_style_chunk("<function_calls>\n"),
            create_gemini_style_chunk('<invoke name="execute_command">\n'),
            create_gemini_style_chunk(
                '<parameter name="command">git diff</parameter>\n'
            ),
            create_gemini_style_chunk("</invoke>\n"),
            create_gemini_style_chunk("</function_calls>"),
            create_gemini_style_chunk(finish_reason="stop"),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        all_text = extract_all_text(result_chunks)

        # Verify structure expected by KiloCode
        assert (
            "I'll check the local uncommitted changes." in all_text
            or "check" in all_text
        )
        assert "execute_command" in all_text
        assert "git diff" in all_text

    @pytest.mark.asyncio
    async def test_wrapper_class_direct_usage(self):
        """Test using VTCResponseStreamWrapper class directly."""
        wrapper = VTCResponseStreamWrapper(
            vtc_enabled=True,
            config=VTCWrapperConfig(max_buffer_bytes=1024),
        )

        chunks = [
            create_gemini_style_chunk("Test message\n\n"),
            create_gemini_style_chunk(
                '<function_calls><invoke name="test">'
                '<parameter name="x">1</parameter>'
                "</invoke></function_calls>"
            ),
            create_gemini_style_chunk(finish_reason="stop"),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrapper.wrap(mock_stream()):
            result_chunks.append(chunk)

        all_text = extract_all_text(result_chunks)
        assert "Test message" in all_text
        assert "test" in all_text

    @pytest.mark.asyncio
    async def test_wrapper_reset_between_streams(self):
        """Test that wrapper can be reset and reused."""
        wrapper = VTCResponseStreamWrapper(vtc_enabled=True)

        # First stream
        async def stream1():
            yield create_gemini_style_chunk("First stream")
            yield create_gemini_style_chunk(finish_reason="stop")

        result1 = []
        async for chunk in wrapper.wrap(stream1()):
            result1.append(chunk)

        # Reset
        wrapper.reset()

        # Second stream
        async def stream2():
            yield create_gemini_style_chunk("Second stream")
            yield create_gemini_style_chunk(finish_reason="stop")

        result2 = []
        async for chunk in wrapper.wrap(stream2()):
            result2.append(chunk)

        # Both should have processed correctly
        assert "First stream" in extract_all_text(result1)
        assert "Second stream" in extract_all_text(result2)
