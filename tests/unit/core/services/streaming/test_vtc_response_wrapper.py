"""
Unit tests for VTCResponseStreamWrapper.

Tests the VTC response stream wrapper that transforms ProcessedResponse streams
with VTC (Virtual Tool Calling) XML processing.
"""

from __future__ import annotations

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse


def create_chunk(
    content_text: str, finish_reason: str | None = None
) -> ProcessedResponse:
    """Helper to create a ProcessedResponse with OpenAI-format content."""
    delta: dict = {"content": content_text}
    if finish_reason:
        delta["finish_reason"] = finish_reason

    return ProcessedResponse(
        content={
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        },
        metadata={"id": "chatcmpl-test", "model": "test-model"},
    )


def create_empty_chunk(finish_reason: str = "stop") -> ProcessedResponse:
    """Helper to create a ProcessedResponse with no text content (final chunk)."""
    return ProcessedResponse(
        content={
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
        },
        metadata={
            "id": "chatcmpl-test",
            "model": "test-model",
            "finish_reason": finish_reason,
        },
    )


def extract_text_from_chunk(chunk: ProcessedResponse) -> str:
    """Extract text content from a ProcessedResponse chunk."""
    content = chunk.content
    if not isinstance(content, dict):
        return ""
    choices = content.get("choices", [])
    if not choices:
        return ""
    delta = choices[0].get("delta", {})
    return delta.get("content", "") or ""


class TestVTCResponseStreamWrapperPassThrough:
    """Tests for pass-through behavior when VTC is disabled."""

    @pytest.mark.asyncio
    async def test_pass_through_when_vtc_disabled(self):
        """When vtc_enabled=False, chunks should pass through unchanged."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        chunks = [
            create_chunk("Hello "),
            create_chunk("world!"),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=False
        ):
            result_chunks.append(chunk)

        assert len(result_chunks) == 3
        assert extract_text_from_chunk(result_chunks[0]) == "Hello "
        assert extract_text_from_chunk(result_chunks[1]) == "world!"

    @pytest.mark.asyncio
    async def test_pass_through_non_text_chunks(self):
        """Chunks without text content should pass through unchanged."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        chunks = [
            create_chunk("Hello"),
            create_empty_chunk(),  # No text content
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Both chunks should come through
        assert len(result_chunks) >= 1


class TestVTCResponseStreamWrapperXMLExtraction:
    """Tests for XML tool call extraction."""

    @pytest.mark.asyncio
    async def test_tool_calls_added_to_metadata_for_reactors(self):
        """Detected tool calls should be added to metadata for reactor processing."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Use simple format (KiloCode style)
        xml_content = (
            "I will run the command.\n\n"
            "<execute_command>\n"
            "<command>git status</command>\n"
            "</execute_command>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Should have output chunks
        assert len(result_chunks) >= 1

        # Find chunk with tool calls in metadata
        tool_calls_found = False
        for chunk in result_chunks:
            if chunk.metadata and chunk.metadata.get("tool_calls"):
                tool_calls_found = True
                tool_calls = chunk.metadata["tool_calls"]
                assert len(tool_calls) == 1
                assert tool_calls[0].function.name == "execute_command"
                # Verify VTC marker is set
                assert chunk.metadata.get("vtc_tool_calls") is True
                break

        assert (
            tool_calls_found
        ), "Tool calls should be in metadata for reactor processing"

    @pytest.mark.asyncio
    async def test_extract_complete_xml_single_chunk(self):
        """Complete XML tool call in single chunk should be processed."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        xml_content = (
            "I will run the command.<function_calls>\n"
            '<invoke name="execute_command">\n'
            '<parameter name="command">ls -la</parameter>\n'
            "</invoke>\n"
            "</function_calls>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Should have processed chunks
        assert len(result_chunks) >= 1

        # Combine all text content
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)

        # The output should contain the original XML (passed through unchanged)
        assert "<function_calls>" in all_text or "<invoke" in all_text

    @pytest.mark.asyncio
    async def test_extract_xml_split_across_chunks(self):
        """XML tool call split across chunks should be buffered and processed."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Split the XML across multiple chunks
        chunks = [
            create_chunk("I will run "),
            create_chunk("the command.<function_calls>\n<invoke "),
            create_chunk('name="execute_command">\n'),
            create_chunk('<parameter name="command">ls</parameter>\n'),
            create_chunk("</invoke>\n</function_calls>"),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Should have output
        assert len(result_chunks) >= 1

        # Combine all text
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)

        # The text prefix should be preserved
        assert "I will run the command." in all_text or "I will run" in all_text


class TestVTCResponseStreamWrapperRoundTrip:
    """Tests for XML round-trip (parse -> internal -> serialize)."""

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_tool_call_structure(self):
        """Tool calls should round-trip correctly: XML -> internal -> XML."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        xml_content = (
            "<function_calls>\n"
            '<invoke name="read_file">\n'
            '<parameter name="path">/tmp/test.txt</parameter>\n'
            "</invoke>\n"
            "</function_calls>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Combine all text
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)

        # Should contain the tool call (re-serialized)
        assert "read_file" in all_text
        assert "path" in all_text

    @pytest.mark.asyncio
    async def test_roundtrip_multiple_tool_calls(self):
        """Multiple tool calls should all be preserved."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        xml_content = (
            "<function_calls>\n"
            '<invoke name="read_file">\n'
            '<parameter name="path">/tmp/a.txt</parameter>\n'
            "</invoke>\n"
            '<invoke name="write_file">\n'
            '<parameter name="path">/tmp/b.txt</parameter>\n'
            '<parameter name="content">Hello</parameter>\n'
            "</invoke>\n"
            "</function_calls>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Combine all text
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)

        # Both tool calls should be present
        assert "read_file" in all_text
        assert "write_file" in all_text


class TestVTCResponseStreamWrapperBuffering:
    """Tests for buffering behavior."""

    @pytest.mark.asyncio
    async def test_buffer_flushed_on_stream_end(self):
        """Any buffered content should be flushed when stream ends."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Incomplete XML at end of stream
        chunks = [
            create_chunk("Hello world"),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Should have output with the text
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)
        assert "Hello world" in all_text

    @pytest.mark.asyncio
    async def test_buffer_overflow_forces_flush(self):
        """Exceeding max buffer size should force a flush."""
        from src.core.services.streaming.vtc_response_wrapper import (
            VTCResponseStreamWrapper,
            VTCWrapperConfig,
        )

        # Create wrapper with small buffer limit
        config = VTCWrapperConfig(max_buffer_bytes=50)
        wrapper = VTCResponseStreamWrapper(vtc_enabled=True, config=config)

        # Create chunks that exceed buffer
        long_text = "A" * 100  # 100 bytes, exceeds 50 byte limit
        chunks = [
            create_chunk(long_text),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrapper.wrap(mock_stream()):
            result_chunks.append(chunk)

        # Should have flushed the content
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)
        assert len(all_text) >= 100


class TestVTCResponseStreamWrapperEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        """Empty stream should yield nothing."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        async def mock_stream():
            return
            yield  # Make it an async generator

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        assert len(result_chunks) == 0

    @pytest.mark.asyncio
    async def test_malformed_xml_passes_through(self):
        """Malformed XML should be passed through without crashing."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Malformed XML (unclosed tags)
        chunks = [
            create_chunk("<function_calls><invoke name='test'>"),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        # Should not crash, content should be present
        assert len(result_chunks) >= 1

    @pytest.mark.asyncio
    async def test_mixed_text_and_xml(self):
        """Text before and after XML should be preserved."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        chunks = [
            create_chunk("Before text. "),
            create_chunk(
                '<function_calls><invoke name="test">'
                '<parameter name="x">1</parameter></invoke></function_calls>'
            ),
            create_chunk(" After text."),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(chunk)

        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)

        # Both surrounding text should be present
        assert "Before text" in all_text
        assert "After text" in all_text

    @pytest.mark.asyncio
    async def test_non_dict_content_passes_through(self):
        """ProcessedResponse with non-dict content should pass through."""
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Create chunk with string content (edge case)
        chunk = ProcessedResponse(
            content="raw string content",
            metadata={},
        )

        async def mock_stream():
            yield chunk

        result_chunks = []
        async for c in wrap_processed_response_stream_with_vtc(
            mock_stream(), vtc_enabled=True
        ):
            result_chunks.append(c)

        # Should pass through
        assert len(result_chunks) >= 1


class TestVTCWrapperConfig:
    """Tests for VTCWrapperConfig."""

    def test_default_config_values(self):
        """Default config should have reasonable values."""
        from src.core.services.streaming.vtc_response_wrapper import VTCWrapperConfig

        config = VTCWrapperConfig()
        assert config.max_buffer_bytes == 64 * 1024
        assert config.emit_partial_on_done is True

    def test_custom_config_values(self):
        """Custom config values should be respected."""
        from src.core.services.streaming.vtc_response_wrapper import VTCWrapperConfig

        config = VTCWrapperConfig(max_buffer_bytes=1024, emit_partial_on_done=False)
        assert config.max_buffer_bytes == 1024
        assert config.emit_partial_on_done is False


class TestVTCReactorIntegration:
    """Tests for tool call reactor integration."""

    @pytest.mark.asyncio
    async def test_reactor_invoked_for_detected_tool_calls(self):
        """Tool call reactor should be invoked when tool calls are detected."""
        from unittest.mock import AsyncMock, MagicMock

        from src.core.interfaces.tool_call_reactor_interface import (
            ToolCallReactionResult,
        )
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Create mock reactor that does NOT swallow (returns proper result)
        mock_result = ToolCallReactionResult(should_swallow=False)
        mock_reactor = MagicMock()
        mock_reactor.process_tool_call = AsyncMock(return_value=mock_result)

        # Use simple format tool call (KiloCode style)
        xml_content = (
            "I will run the command.\n\n"
            "<execute_command>\n"
            "<command>git status</command>\n"
            "</execute_command>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(),
            vtc_enabled=True,
            tool_call_reactor=mock_reactor,
            session_id="test-session-123",
            context={"backend_name": "test-backend", "model_name": "test-model"},
        ):
            result_chunks.append(chunk)

        # Verify reactor was called
        assert (
            mock_reactor.process_tool_call.called
        ), "Reactor should be invoked for detected tool calls"

        # Check the context passed to reactor
        call_args = mock_reactor.process_tool_call.call_args
        context = call_args[0][0]  # First positional argument
        assert context.session_id == "test-session-123"
        assert context.tool_name == "execute_command"
        assert context.backend_name == "test-backend"

    @pytest.mark.asyncio
    async def test_reactor_not_invoked_when_no_tool_calls(self):
        """Reactor should NOT be invoked when no tool calls are detected."""
        from unittest.mock import AsyncMock, MagicMock

        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Create mock reactor
        mock_reactor = MagicMock()
        mock_reactor.process_tool_call = AsyncMock(return_value=MagicMock())

        # Plain text without tool calls
        chunks = [
            create_chunk("This is just plain text without any tool calls."),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(),
            vtc_enabled=True,
            tool_call_reactor=mock_reactor,
            session_id="test-session",
        ):
            result_chunks.append(chunk)

        # Reactor should NOT be called
        assert not mock_reactor.process_tool_call.called

    @pytest.mark.asyncio
    async def test_reactor_not_invoked_when_vtc_disabled(self):
        """Reactor should NOT be invoked when VTC is disabled."""
        from unittest.mock import AsyncMock, MagicMock

        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Create mock reactor
        mock_reactor = MagicMock()
        mock_reactor.process_tool_call = AsyncMock(return_value=MagicMock())

        # Tool call XML (but VTC disabled)
        xml_content = "<execute_command><command>test</command></execute_command>"
        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(),
            vtc_enabled=False,  # VTC disabled
            tool_call_reactor=mock_reactor,
            session_id="test-session",
        ):
            result_chunks.append(chunk)

        # Reactor should NOT be called (VTC disabled)
        assert not mock_reactor.process_tool_call.called

    @pytest.mark.asyncio
    async def test_tool_call_swallowed_does_not_leak_replacement_message(self):
        """When reactor swallows a tool call, replacement message must not reach the client."""
        from unittest.mock import AsyncMock, MagicMock

        from src.core.interfaces.tool_call_reactor_interface import (
            ToolCallReactionResult,
        )
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Create mock reactor that swallows the tool call
        mock_result = ToolCallReactionResult(
            should_swallow=True,
            replacement_response="[BLOCKED] This tool call is not allowed by policy.",
            metadata={"handler": "test_handler"},
        )
        mock_reactor = MagicMock()
        mock_reactor.process_tool_call = AsyncMock(return_value=mock_result)

        # Use simple format tool call
        xml_content = (
            "I will run the command.\n\n"
            "<execute_command>\n"
            "<command>rm -rf /</command>\n"
            "</execute_command>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(),
            vtc_enabled=True,
            tool_call_reactor=mock_reactor,
            session_id="test-session-123",
            context={"backend_name": "test-backend", "model_name": "test-model"},
        ):
            result_chunks.append(chunk)

        # Combine all text content
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)

        # The replacement message must NOT be in the output (it is meant for the remote model)
        assert (
            "[BLOCKED]" not in all_text
        ), "Replacement message must not be client-visible"

        # The original XML should NOT be in the output (it was stripped)
        assert "<execute_command>" not in all_text, "Original XML should be stripped"
        assert "rm -rf /" not in all_text, "Original command should be stripped"

        # Check metadata indicates swallowing occurred and carries steering_message for retry logic
        swallow_found = False
        for chunk in result_chunks:
            if chunk.metadata and chunk.metadata.get("tool_call_swallowed"):
                swallow_found = True
                assert "steering_message" in chunk.metadata
                break
        assert swallow_found, "Metadata should indicate tool call was swallowed"

    @pytest.mark.asyncio
    async def test_partial_tool_call_swallowing(self):
        """When some tool calls are swallowed and others pass through."""
        from unittest.mock import AsyncMock, MagicMock

        from src.core.interfaces.tool_call_reactor_interface import (
            ToolCallReactionResult,
        )
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Create mock reactor that only swallows 'dangerous_command'
        def mock_process_tool_call(context):
            if context.tool_name == "dangerous_command":
                return ToolCallReactionResult(
                    should_swallow=True,
                    replacement_response="[BLOCKED] Dangerous command not allowed.",
                )
            return ToolCallReactionResult(should_swallow=False)

        mock_reactor = MagicMock()
        mock_reactor.process_tool_call = AsyncMock(side_effect=mock_process_tool_call)

        # Two tool calls - one should be blocked
        xml_content = (
            "Let me run some commands.\n\n"
            "<function_calls>\n"
            '<invoke name="safe_command">\n'
            '<parameter name="cmd">ls -la</parameter>\n'
            "</invoke>\n"
            '<invoke name="dangerous_command">\n'
            '<parameter name="cmd">rm -rf /</parameter>\n'
            "</invoke>\n"
            "</function_calls>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(),
            vtc_enabled=True,
            tool_call_reactor=mock_reactor,
            session_id="test-session-123",
        ):
            result_chunks.append(chunk)

        # Combine all text content
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)

        # Replacement messages must not leak to the client
        assert "[BLOCKED]" not in all_text

        # Verify reactor was called twice (once per tool call)
        assert mock_reactor.process_tool_call.call_count == 2

    @pytest.mark.asyncio
    async def test_non_swallowed_tool_calls_pass_through_unchanged(self):
        """Tool calls that are not swallowed should pass through unchanged."""
        from unittest.mock import AsyncMock, MagicMock

        from src.core.interfaces.tool_call_reactor_interface import (
            ToolCallReactionResult,
        )
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Create mock reactor that does NOT swallow
        mock_result = ToolCallReactionResult(
            should_swallow=False,
            metadata={"handler": "test_handler", "decision": "allowed"},
        )
        mock_reactor = MagicMock()
        mock_reactor.process_tool_call = AsyncMock(return_value=mock_result)

        xml_content = (
            "I will run the command.\n\n"
            "<execute_command>\n"
            "<command>git status</command>\n"
            "</execute_command>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(),
            vtc_enabled=True,
            tool_call_reactor=mock_reactor,
            session_id="test-session-123",
        ):
            result_chunks.append(chunk)

        # Combine all text content
        all_text = "".join(extract_text_from_chunk(c) for c in result_chunks)

        # Original content should be preserved (including XML)
        assert "<execute_command>" in all_text or "execute_command" in all_text
        assert "git status" in all_text

        # No swallowing metadata
        for chunk in result_chunks:
            if chunk.metadata:
                assert not chunk.metadata.get("vtc_tool_calls_swallowed")

    @pytest.mark.asyncio
    async def test_vtc_uses_standardized_argument_contract(self):
        """VTC wrapper should use standardized argument parsing/fixup pipeline."""
        from unittest.mock import AsyncMock, MagicMock

        from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
            FixupContext,
            IToolArgumentsFixupPipeline,
        )
        from src.core.interfaces.tool_arguments_parser_interface import (
            IToolArgumentsParser,
        )
        from src.core.interfaces.tool_call_reactor_interface import (
            ToolCallReactionResult,
        )
        from src.core.interfaces.tool_call_reactor_internal import (
            NormalizedToolArguments,
            ToolArgumentsEnvelope,
        )
        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        # Create mock parser and fixup pipeline
        mock_parser = MagicMock(spec=IToolArgumentsParser)
        mock_fixup = MagicMock(spec=IToolArgumentsFixupPipeline)

        # Mock parser to return an envelope
        mock_envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments({"command": "git status"}),
        )
        mock_parser.parse.return_value = mock_envelope

        # Mock fixup to return the same envelope (no modifications)
        mock_fixup.apply_fixups.return_value = mock_envelope

        # Create mock reactor that does NOT swallow
        mock_result = ToolCallReactionResult(should_swallow=False)
        mock_reactor = MagicMock()
        mock_reactor.process_tool_call = AsyncMock(return_value=mock_result)

        xml_content = (
            "I will run the command.\n\n"
            "<execute_command>\n"
            "<command>git status</command>\n"
            "</execute_command>"
        )

        chunks = [
            create_chunk(xml_content),
            create_empty_chunk(),
        ]

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        result_chunks = []
        async for chunk in wrap_processed_response_stream_with_vtc(
            mock_stream(),
            vtc_enabled=True,
            tool_call_reactor=mock_reactor,
            arguments_parser=mock_parser,
            arguments_fixup_pipeline=mock_fixup,
            session_id="test-session",
            context={"backend_name": "test-backend", "model_name": "test-model"},
        ):
            result_chunks.append(chunk)

        # Verify parser was called with raw arguments
        assert mock_parser.parse.called
        call_args = mock_parser.parse.call_args[0]
        assert isinstance(call_args[0], str | dict)

        # Verify fixup pipeline was called with envelope and context
        assert mock_fixup.apply_fixups.called
        fixup_call_args = mock_fixup.apply_fixups.call_args
        assert isinstance(fixup_call_args[0][0], ToolArgumentsEnvelope)
        assert isinstance(fixup_call_args[0][1], FixupContext)
        assert fixup_call_args[0][1].tool_name == "execute_command"
        assert fixup_call_args[0][1].backend_name == "test-backend"

        # Verify reactor was called with normalized arguments
        assert mock_reactor.process_tool_call.called
        reactor_context = mock_reactor.process_tool_call.call_args[0][0]
        assert reactor_context.tool_arguments == {"command": "git status"}
