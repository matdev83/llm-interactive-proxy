"""
Regression tests for tool call handling in the streaming pipeline.

These tests cover:

1. ToolCallRepairProcessor buffering: Ensures that truncated XML tool calls
   are properly buffered until complete, preventing premature parsing of
   inner tags.

2. Session ID correlation: Ensures that streaming chunks with different 'id'
   fields but the same 'session_id' are properly correlated for buffering.

3. Synthetic closing tag injection: Tests that truncated XML at end-of-stream
   gets synthetic closing tags to allow parsing.

4. XML leakage prevention: Tests that partial XML tags are not emitted to
   the client.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


class TestToolCallRepairProcessorBuffering:
    """
    Tests for the ToolCallRepairProcessor's buffering behavior.

    The processor should buffer content until a complete tool call is detected,
    preventing premature parsing of inner tags.
    """

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(
        self, repair_service: ToolCallRepairService, registry: StreamingContextRegistry
    ) -> ToolCallRepairProcessor:
        return ToolCallRepairProcessor(
            repair_service, max_buffer_bytes=64 * 1024, registry=registry
        )

    @pytest.mark.asyncio
    async def test_truncated_execute_command_is_buffered(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        CRITICAL REGRESSION TEST: Truncated execute_command should be buffered.

        When the first chunk contains a truncated <execute_command>, the processor
        should NOT emit a tool call with name='command'. Instead, it should buffer
        the content until the complete XML is received.
        """
        # First chunk: truncated XML
        chunk1 = StreamingContent(
            content="""I will run the test suite.
<execute_command>
<command>./.venv/Scripts""",
            is_done=False,
            metadata={"session_id": "test-session"},
        )

        result1 = await processor.process(chunk1)

        # The processor should NOT emit a tool call yet
        tool_calls = result1.metadata.get("tool_calls") if result1.metadata else None
        assert (
            tool_calls is None or len(tool_calls) == 0
        ), f"Truncated XML should NOT produce tool calls! Got: {tool_calls}"

        # If a tool call was incorrectly detected, check it's not 'command'
        if tool_calls:
            for tc in tool_calls:
                assert (
                    tc["function"]["name"] != "command"
                ), "Inner tag 'command' was incorrectly parsed as a tool call!"

    @pytest.mark.asyncio
    async def test_complete_execute_command_produces_tool_call(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Test that complete execute_command produces a tool call."""
        chunk = StreamingContent(
            content="""<execute_command>
<command>./.venv/Scripts/python.exe -m pytest</command>
</execute_command>""",
            is_done=True,
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(chunk)

        tool_calls = result.metadata.get("tool_calls") if result.metadata else None
        assert (
            tool_calls is not None and len(tool_calls) > 0
        ), "Complete execute_command should produce a tool call"
        assert tool_calls[0]["function"]["name"] == "execute_command"

    @pytest.mark.asyncio
    async def test_multi_chunk_execute_command(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        Test that execute_command split across multiple chunks is handled correctly.
        """
        # Chunk 1: Start of command
        chunk1 = StreamingContent(
            content="""I will run the tests.
<execute_command>
<command>./.venv/Scripts""",
            is_done=False,
            metadata={"session_id": "test-session"},
        )

        result1 = await processor.process(chunk1)
        tool_calls1 = result1.metadata.get("tool_calls") if result1.metadata else None
        assert (
            tool_calls1 is None or len(tool_calls1) == 0
        ), "First chunk should not produce tool call"

        # Chunk 2: Completion of command
        chunk2 = StreamingContent(
            content="""/python.exe -m pytest</command>
</execute_command>""",
            is_done=True,
            metadata={"session_id": "test-session"},
        )

        result2 = await processor.process(chunk2)
        tool_calls2 = result2.metadata.get("tool_calls") if result2.metadata else None
        assert (
            tool_calls2 is not None and len(tool_calls2) > 0
        ), "Second chunk should produce tool call after buffering"
        assert tool_calls2[0]["function"]["name"] == "execute_command"
        arguments = json.loads(tool_calls2[0]["function"]["arguments"])
        assert "./.venv/Scripts/python.exe -m pytest" in arguments["command"]

    @pytest.mark.asyncio
    async def test_truncated_read_file_is_buffered(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Test that truncated read_file is buffered."""
        chunk = StreamingContent(
            content="""<read_file>
<file>src/main""",
            is_done=False,
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(chunk)
        tool_calls = result.metadata.get("tool_calls") if result.metadata else None

        # Should NOT produce a tool call with name='file'
        if tool_calls:
            for tc in tool_calls:
                assert (
                    tc["function"]["name"] != "file"
                ), "Inner tag 'file' was incorrectly parsed as a tool call!"

    @pytest.mark.asyncio
    async def test_existing_tool_calls_are_deduped(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Ensure tool_calls already present in metadata are not duplicated."""

        existing_call = {
            "id": "call_existing",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path": "scripts/demo.py"}',
            },
        }

        chunk = StreamingContent(
            content="""<read_file>
<args>
  <file>
    <path>scripts/demo.py</path>
  </file>
</args>
</read_file>""",
            is_done=True,
            metadata={"session_id": "test-session", "tool_calls": [existing_call]},
        )

        result = await processor.process(chunk)

        tool_calls = result.metadata.get("tool_calls") if result.metadata else None
        assert tool_calls is not None
        assert len(tool_calls) == 1, f"Expected deduped tool_calls, got {tool_calls}"
        assert tool_calls[0]["function"]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_truncated_ask_followup_question_is_buffered(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        Test that truncated ask_followup_question is buffered.

        This was the original bug causing "What can I help you with today?</"
        to leak.
        """
        chunk = StreamingContent(
            content="""Hello! I'm Kilo Code.
<ask_followup_question>
<question>What can I help you with today?</""",
            is_done=False,
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(chunk)
        tool_calls = result.metadata.get("tool_calls") if result.metadata else None

        # Should NOT produce a tool call with name='question'
        if tool_calls:
            for tc in tool_calls:
                assert (
                    tc["function"]["name"] != "question"
                ), "Inner tag 'question' was incorrectly parsed as a tool call!"


class TestSyntheticClosingTagInjection:
    """
    Tests for synthetic closing tag injection at end-of-stream.

    When a stream ends with truncated XML that has the inner tag complete but
    is missing the outer closing tag, the processor should inject synthetic
    closing tags to allow parsing of the tool call.
    """

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(
        self, repair_service: ToolCallRepairService, registry: StreamingContextRegistry
    ) -> ToolCallRepairProcessor:
        return ToolCallRepairProcessor(
            repair_service, max_buffer_bytes=64 * 1024, registry=registry
        )

    @pytest.mark.asyncio
    async def test_synthetic_closing_for_execute_command(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Test that truncated execute_command at EOS gets synthetic closing.

        Note: The synthetic closing only works when the inner tag is complete
        but the outer tag is missing. If both are truncated, it cannot be parsed.
        """
        # Single chunk with truncated XML - inner tag complete, outer tag missing
        chunk = StreamingContent(
            content="""<execute_command>
<command>./.venv/Scripts/python.exe -m pytest</command>""",
            is_done=True,  # Stream ends with truncated XML
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(chunk)
        tool_calls = result.metadata.get("tool_calls") if result.metadata else None

        # Should have injected synthetic </execute_command> and parsed the tool call
        assert (
            tool_calls is not None and len(tool_calls) > 0
        ), "Synthetic closing should allow parsing truncated execute_command at EOS"
        assert tool_calls[0]["function"]["name"] == "execute_command"

    @pytest.mark.asyncio
    async def test_synthetic_closing_for_read_file(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Test that truncated read_file at EOS gets synthetic closing."""
        # Single chunk with truncated XML - inner tag complete, outer tag missing
        chunk = StreamingContent(
            content="""<read_file>
<file>src/main.py</file>""",
            is_done=True,  # Stream ends with truncated XML
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(chunk)
        tool_calls = result.metadata.get("tool_calls") if result.metadata else None

        assert (
            tool_calls is not None and len(tool_calls) > 0
        ), "Synthetic closing should allow parsing truncated read_file at EOS"
        assert tool_calls[0]["function"]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_fully_truncated_xml_with_synthetic_closing(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Test that fully truncated XML (both inner and outer tags missing) IS parsed.

        The processor should inject BOTH the inner closing tag (</command>)
        AND the outer closing tag (</execute_command>) to allow parsing.
        """
        # Both inner and outer tags are truncated
        chunk = StreamingContent(
            content="""<execute_command>
<command>./.venv/Scripts/python.exe -m pytest""",
            is_done=True,
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(chunk)
        tool_calls = result.metadata.get("tool_calls") if result.metadata else None

        # With the fix, fully truncated XML SHOULD be parsed
        # The processor injects both </command> and </execute_command>
        assert (
            tool_calls is not None and len(tool_calls) > 0
        ), "Fully truncated XML should be parsed with synthetic inner+outer closing tags"
        assert tool_calls[0]["function"]["name"] == "execute_command"
        arguments = json.loads(tool_calls[0]["function"]["arguments"])
        assert "./.venv/Scripts/python.exe -m pytest" in arguments["command"]

    @pytest.mark.asyncio
    async def test_truncated_new_task_repaired_with_allowed_tools(
        self,
        processor: ToolCallRepairProcessor,
        registry: StreamingContextRegistry,
    ) -> None:
        """
        Ensure truncated new_task XML is repaired when allowed tools are set,
        and does not incorrectly emit inner parameter tags as tool calls.
        """
        session_id = "new-task-session"
        registry.get_tool_call_buffer(session_id).allowed_tools = ["new_task"]

        initial_chunk = StreamingContent(
            content="<new_task>\n<mode>code</mode>\n<message>Fix cleanliness tests",
            is_done=False,
            metadata={"session_id": session_id},
        )

        intermediate = await processor.process(initial_chunk)
        tool_calls = (
            intermediate.metadata.get("tool_calls") if intermediate.metadata else None
        )
        assert not tool_calls, f"Unexpected tool calls detected early: {tool_calls}"

        final_chunk = await processor.process(
            StreamingContent(
                content="", is_done=True, metadata={"session_id": session_id}
            )
        )

        final_tool_calls = (
            final_chunk.metadata.get("tool_calls") if final_chunk.metadata else None
        )
        assert final_tool_calls, "Expected repaired new_task tool call at end-of-stream"
        tool_call = cast(dict[str, Any], final_tool_calls[0])
        assert tool_call["function"]["name"] == "new_task"

        arguments = json.loads(tool_call["function"]["arguments"])
        assert arguments.get("mode") == "code"
        assert "Fix cleanliness tests" in arguments.get("message", "")
        assert final_chunk.metadata.get("finish_reason") == "tool_calls"


class TestDynamicToolTagBuffering:
    """Dynamic tool tags should be buffered without hardcoded lists."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(
        self, repair_service: ToolCallRepairService, registry: StreamingContextRegistry
    ) -> ToolCallRepairProcessor:
        return ToolCallRepairProcessor(
            repair_service, max_buffer_bytes=64 * 1024, registry=registry
        )

    @pytest.mark.asyncio
    async def test_dynamic_tag_from_allowed_tools(
        self, processor: ToolCallRepairProcessor, registry: StreamingContextRegistry
    ) -> None:
        session_id = "dynamic-tools"
        registry.get_tool_call_buffer(session_id).allowed_tools = ["custom_tool"]

        first = StreamingContent(
            content="Prep <custom_tool><param>value",
            is_done=False,
            metadata={"session_id": session_id},
        )
        interim = await processor.process(first)
        assert not interim.metadata.get("tool_calls")

        final = await processor.process(
            StreamingContent(
                content="</param></custom_tool>",
                is_done=True,
                metadata={"session_id": session_id},
            )
        )
        calls = final.metadata.get("tool_calls") if final.metadata else None
        assert calls and calls[0]["function"]["name"] == "custom_tool"

    def test_think_tags_ignored_without_allowed_tools(self) -> None:
        repair_service = ToolCallRepairService()
        result = repair_service.repair_tool_calls(
            "<think>hello</think>", allowed_tools=[]
        )
        assert result is None


class TestStreamKeyResolution:
    """
    Tests for stream key resolution in response adapters.

    The stream key is used to correlate streaming chunks for buffering.
    It MUST use session_id or stream_id, NOT the per-chunk 'id' field.
    """

    def test_stream_key_uses_session_id_not_chunk_id(self) -> None:
        """
        CRITICAL REGRESSION TEST: Stream key must use session_id, not chunk id.

        Bug description: When chunks have different 'id' fields (as with Gemini),
        using 'id' for buffering correlation would cause tool calls to be split
        incorrectly.
        """
        import inspect

        from src.core.transport.fastapi import response_adapters

        source = inspect.getsource(response_adapters.to_fastapi_streaming_response)

        # Check that _resolve_stream_key prioritizes session_id/stream_id
        assert "session_id" in source, "_resolve_stream_key must check for session_id"
        assert "stream_id" in source, "_resolve_stream_key must check for stream_id"

        # Check the comment warning about not using 'id'
        assert (
            "NOT use" in source
            or "not use" in source.lower()
            or "NOT suitable" in source
        ), "Code should document that 'id' is NOT suitable for buffering"

    def test_buffered_tool_tags_includes_critical_tags(self) -> None:
        """Ensure streaming adapter relies on dynamic tags, not hardcoded lists."""
        import inspect

        from src.core.transport.fastapi import response_adapters

        source = inspect.getsource(response_adapters.to_fastapi_streaming_response)
        # Dynamic approach should reference allowed_tools or tracked_tags
        assert "allowed_tools" in source
        assert "tracked_tags" in source


class TestToolCallMetadataMarkers:
    """
    Tests for tool call metadata markers and deduplication.

    The _already_processed marker is used internally to prevent duplicate processing
    of tool calls across different pipeline stages. It is sanitized before returning
    to the caller to keep the metadata clean.
    """

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(
        self, repair_service: ToolCallRepairService, registry: StreamingContextRegistry
    ) -> ToolCallRepairProcessor:
        return ToolCallRepairProcessor(
            repair_service, max_buffer_bytes=64 * 1024, registry=registry
        )

    @pytest.mark.asyncio
    async def test_tool_call_has_required_fields(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Test that detected tool calls have required OpenAI-compatible fields."""
        chunk = StreamingContent(
            content="""<execute_command>
<command>ls -la</command>
</execute_command>""",
            is_done=True,
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(chunk)
        tool_calls = result.metadata.get("tool_calls") if result.metadata else None

        assert tool_calls is not None and len(tool_calls) > 0
        # Check for required OpenAI-compatible fields
        assert "id" in tool_calls[0], "Tool call should have 'id' field"
        assert "type" in tool_calls[0], "Tool call should have 'type' field"
        assert "function" in tool_calls[0], "Tool call should have 'function' field"
        assert tool_calls[0]["type"] == "function"
        assert tool_calls[0]["function"]["name"] == "execute_command"

    @pytest.mark.asyncio
    async def test_tool_calls_are_detected_in_each_chunk(
        self, processor: ToolCallRepairProcessor, registry: StreamingContextRegistry
    ) -> None:
        """Test that tool calls in different chunks are detected.

        Note: Each chunk is processed independently, so the same tool call
        in different chunks will be detected multiple times. Deduplication
        happens at a higher level (e.g., in the reactor middleware).
        """
        session_id = "test-session-multi"

        # First chunk with a tool call
        chunk1 = StreamingContent(
            content="""<execute_command>
<command>ls -la</command>
</execute_command>""",
            is_done=False,
            metadata={"session_id": session_id},
        )

        result1 = await processor.process(chunk1)
        tool_calls1: list[dict[str, Any]] = (
            cast(list[dict[str, Any]], result1.metadata.get("tool_calls"))
            if result1.metadata
            else []
        )

        # Second chunk with a DIFFERENT tool call
        chunk2 = StreamingContent(
            content="""<execute_command>
<command>pwd</command>
</execute_command>""",
            is_done=True,
            metadata={"session_id": session_id},
        )

        result2 = await processor.process(chunk2)
        tool_calls2: list[dict[str, Any]] = (
            cast(list[dict[str, Any]], result2.metadata.get("tool_calls"))
            if result2.metadata
            else []
        )

        # Both tool calls should be detected
        assert len(tool_calls1) == 1, "First chunk should have one tool call"
        assert len(tool_calls2) == 1, "Second chunk should have one tool call"
        assert tool_calls1[0]["function"]["name"] == "execute_command"
        assert tool_calls2[0]["function"]["name"] == "execute_command"

        # Arguments should be different
        args1 = json.loads(tool_calls1[0]["function"]["arguments"])
        args2 = json.loads(tool_calls2[0]["function"]["arguments"])
        assert args1["command"] == "ls -la"
        assert args2["command"] == "pwd"


class TestInnerTagSkipList:
    """
    Tests to verify that the inner tag skip list in ToolCallRepairService
    is comprehensive.
    """

    def test_skip_list_includes_all_inner_tags(self) -> None:
        """Verify the skip list includes all known inner tags."""
        import ast
        import inspect

        from src.core.services import tool_call_repair_service

        source = inspect.getsource(tool_call_repair_service)
        tree = ast.parse(source)

        # Find the skip list (it's a set literal in _extract_xml_tool_call)
        skip_tags: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Set):
                for elt in node.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        skip_tags.append(elt.value)

        # These are the inner tags that MUST be skipped
        required_skip_tags = [
            "command",  # execute_command
            "file",  # read_file, write_to_file
            "question",  # ask_followup_question
            "result",  # attempt_completion
            "regex",  # search_files
            "query",  # codebase_search
            "uri",  # access_mcp_resource
            "server_name",  # MCP tools
            "directory",  # list_files
            "recursive",  # list_files
        ]

        for tag in required_skip_tags:
            assert tag in skip_tags, (
                f"Inner tag '{tag}' MUST be in the skip list to prevent "
                f"incorrect parsing! Found skip tags: {skip_tags}"
            )


class TestEndToEndToolCallFlow:
    """
    End-to-end tests for the complete tool call flow.

    These tests simulate the full streaming pipeline behavior.
    """

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(
        self, repair_service: ToolCallRepairService, registry: StreamingContextRegistry
    ) -> ToolCallRepairProcessor:
        return ToolCallRepairProcessor(
            repair_service, max_buffer_bytes=64 * 1024, registry=registry
        )

    @pytest.mark.asyncio
    async def test_gemini_style_chunking(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        Test Gemini-style chunking where chunks have different IDs.

        This simulates the exact scenario from the wire capture where
        tool calls were being split incorrectly.
        """
        session_id = "test-session-gemini"

        # Chunk 1: Start of command (with one ID)
        chunk1 = StreamingContent(
            content="""I will run the test suite.
<execute_command>
<command>./.venv/Scripts""",
            is_done=False,
            metadata={
                "session_id": session_id,
                "id": "chatcmpl-663a40db142b4bc7",  # Different ID
            },
        )

        result1 = await processor.process(chunk1)
        tool_calls1 = result1.metadata.get("tool_calls") if result1.metadata else None

        # Should NOT have tool call yet
        assert tool_calls1 is None or len(tool_calls1) == 0

        # Chunk 2: Completion of command (with DIFFERENT ID)
        chunk2 = StreamingContent(
            content="""/python.exe -m pytest</command>
</execute_command>""",
            is_done=True,
            metadata={
                "session_id": session_id,  # Same session_id
                "id": "chatcmpl-ef671950e3f24896",  # DIFFERENT ID!
            },
        )

        result2 = await processor.process(chunk2)
        tool_calls2 = result2.metadata.get("tool_calls") if result2.metadata else None

        # Should have the complete tool call
        assert (
            tool_calls2 is not None and len(tool_calls2) > 0
        ), "Tool call should be detected after second chunk"
        assert tool_calls2[0]["function"]["name"] == "execute_command"
        arguments = json.loads(tool_calls2[0]["function"]["arguments"])
        assert (
            "./.venv/Scripts/python.exe -m pytest" in arguments["command"]
        ), f"Full command should be present! Got: {arguments}"

    @pytest.mark.asyncio
    async def test_openai_style_chunking(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        Test OpenAI-style chunking where all chunks have the same ID.
        """
        stream_id = "chatcmpl-test-stream"

        chunks = [
            "I will ",
            "run the ",
            "test suite.\n",
            "<execute_command>\n",
            "<command>./.venv/Scripts/",
            "python.exe -m pytest",
            "</command>\n",
            "</execute_command>",
        ]

        tool_call_found = False
        for i, content in enumerate(chunks):
            is_done = i == len(chunks) - 1
            chunk = StreamingContent(
                content=content,
                is_done=is_done,
                metadata={"session_id": stream_id, "id": stream_id},
            )

            result = await processor.process(chunk)
            tool_calls = result.metadata.get("tool_calls") if result.metadata else None

            if tool_calls and len(tool_calls) > 0:
                tool_call_found = True
                assert tool_calls[0]["function"]["name"] == "execute_command"

        assert tool_call_found, "Tool call should be detected in OpenAI-style chunking"


class TestToolCallsInjectionIntoOpenAIFormat:
    """
    Tests for tool_calls injection when content is already OpenAI-formatted.

    This tests a critical bug fix where tool_calls in metadata were NOT being
    injected into OpenAI-formatted content dicts in StreamingContent.to_bytes().
    """

    def test_tool_calls_injected_when_content_is_openai_dict(self) -> None:
        """Test that tool_calls from metadata are injected into OpenAI-formatted content."""
        openai_content = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-pro",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Running tests now."},
                    "finish_reason": None,
                }
            ],
        }

        tool_calls = [
            {
                "id": "call_test123",
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "arguments": '{"command": "./.venv/Scripts/python.exe -m pytest"}',
                },
            }
        ]

        chunk = StreamingContent(
            content=openai_content,
            metadata={"tool_calls": tool_calls},
            is_done=False,
        )

        result_bytes = chunk.to_bytes()
        result_str = result_bytes.decode("utf-8")

        # Parse the JSON from the SSE format
        assert result_str.startswith("data: ")
        json_str = result_str.replace("data: ", "").strip()
        parsed = json.loads(json_str)

        # Verify tool_calls were injected
        assert "choices" in parsed
        assert len(parsed["choices"]) > 0
        delta = parsed["choices"][0].get("delta", {})
        assert (
            "tool_calls" in delta
        ), f"tool_calls should be injected into delta! Got: {delta}"
        assert delta["tool_calls"] == tool_calls

    def test_tool_calls_injected_when_content_is_openai_dict_and_is_done(self) -> None:
        """Test tool_calls injection when is_done=True and content is OpenAI-formatted."""
        openai_content = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-pro",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": "stop",
                }
            ],
        }

        tool_calls = [
            {
                "id": "call_test456",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"args": {"file": {"path": "README.md"}}}',
                },
            }
        ]

        chunk = StreamingContent(
            content=openai_content,
            metadata={"tool_calls": tool_calls},
            is_done=True,
        )

        result_bytes = chunk.to_bytes()
        result_str = result_bytes.decode("utf-8")

        # Should have both content and [DONE]
        assert "data: [DONE]" in result_str

        # Extract the JSON part (before [DONE])
        lines = result_str.strip().split("\n\n")
        json_line = lines[0]
        assert json_line.startswith("data: ")
        json_str = json_line.replace("data: ", "").strip()
        parsed = json.loads(json_str)

        # Verify tool_calls were injected
        delta = parsed["choices"][0].get("delta", {})
        assert (
            "tool_calls" in delta
        ), f"tool_calls should be injected when is_done=True! Got: {delta}"
        assert delta["tool_calls"] == tool_calls

    def test_no_tool_calls_when_metadata_has_none(self) -> None:
        """Test that nothing is injected when metadata has no tool_calls."""
        openai_content = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-pro",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": None,
                }
            ],
        }

        chunk = StreamingContent(
            content=openai_content,
            metadata={},
            is_done=False,
        )

        result_bytes = chunk.to_bytes()
        result_str = result_bytes.decode("utf-8")

        json_str = result_str.replace("data: ", "").strip()
        parsed = json.loads(json_str)

        delta = parsed["choices"][0].get("delta", {})
        assert (
            "tool_calls" not in delta
        ), "tool_calls should NOT be present when metadata has none"


class TestInternalMarkersSanitization:
    """
    Tests for sanitization of internal markers like _already_processed.

    These markers are used internally for deduplication and loop detection,
    but MUST NOT be sent to the client.
    """

    def test_already_processed_marker_is_removed_from_output(self) -> None:
        """Test that _already_processed marker is removed before sending to client."""
        tool_calls = [
            {
                "id": "call_test123",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path": "README.md"}',
                },
                "_already_processed": True,  # Internal marker that should be removed
            }
        ]

        chunk = StreamingContent(
            content="Reading file...",
            metadata={"tool_calls": tool_calls},
            is_done=True,
        )

        result = chunk.to_bytes().decode("utf-8")

        # Verify tool_calls are present
        assert "tool_calls" in result, "tool_calls should be in output"

        # Verify _already_processed is NOT present
        assert (
            "_already_processed" not in result
        ), "_already_processed marker should be sanitized from output!"

        # Parse and verify structure
        for line in result.strip().split("\n\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                parsed = json.loads(line[6:])
                delta = parsed.get("choices", [{}])[0].get("delta", {})
                if "tool_calls" in delta:
                    for tc in delta["tool_calls"]:
                        assert (
                            "_already_processed" not in tc
                        ), f"Internal marker found in tool call: {tc}"

    def test_multiple_internal_markers_are_removed(self) -> None:
        """Test that all internal markers (starting with _) are removed."""
        tool_calls = [
            {
                "id": "call_test123",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
                "_already_processed": True,
                "_internal_state": "some_value",
                "_debug_info": {"timestamp": 12345},
            }
        ]

        chunk = StreamingContent(
            content="Test",
            metadata={"tool_calls": tool_calls},
            is_done=True,
        )

        result = chunk.to_bytes().decode("utf-8")

        # No internal markers should be present
        assert "_already_processed" not in result
        assert "_internal_state" not in result
        assert "_debug_info" not in result

    def test_openai_formatted_content_also_sanitized(self) -> None:
        """Test that OpenAI-formatted content also has markers sanitized."""
        tool_calls = [
            {
                "id": "call_test",
                "type": "function",
                "function": {"name": "test", "arguments": "{}"},
                "_already_processed": True,
            }
        ]

        openai_content = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello"},
                    "finish_reason": "stop",
                }
            ],
        }

        chunk = StreamingContent(
            content=openai_content,
            metadata={"tool_calls": tool_calls},
            is_done=True,
        )

        result = chunk.to_bytes().decode("utf-8")

        # Tool calls should be injected
        assert "tool_calls" in result

        # But internal markers should be removed
        assert "_already_processed" not in result


class TestFinishReasonOverrideRegression:
    """
    Regression tests for finish_reason override behavior.

    These tests ensure that when tool calls are detected, the finish_reason
    is correctly set to 'tool_calls' regardless of what the backend sent.

    This is critical because clients like Kilo-Code rely on finish_reason
    to determine if they should execute tool calls.

    Bug context: The backend (e.g., Gemini) may send finish_reason: 'stop'
    even when returning tool call XML in the content. The proxy must override
    this to 'tool_calls' so clients recognize the response as a tool call.
    """

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(
        self, repair_service: ToolCallRepairService, registry: StreamingContextRegistry
    ) -> ToolCallRepairProcessor:
        return ToolCallRepairProcessor(
            repair_service, max_buffer_bytes=64 * 1024, registry=registry
        )

    @pytest.mark.asyncio
    async def test_gemini_style_stop_overridden_to_tool_calls(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        CRITICAL REGRESSION TEST: Gemini sends finish_reason: 'stop' with tool calls.

        This test reproduces the exact bug scenario from the wire capture:
        - Backend sends: finish_reason: 'stop' but content has tool call XML
        - Proxy must output: finish_reason: 'tool_calls'

        If this test fails, clients will not execute tool calls even though
        the LLM requested them.
        """
        # Simulate Gemini-style chunk with finish_reason: 'stop' and tool call XML
        chunk = StreamingContent(
            content="""To understand what this project is about, I will start by reading the main documentation file.

<read_file>
<path>README.md</path>
</read_file>""",
            is_done=True,
            metadata={
                "session_id": "gemini-regression-test",
                "finish_reason": "stop",  # This is what Gemini sends - MUST be overridden
                "id": "chatcmpl-test",
                "model": "gemini-2.5-pro",
            },
        )

        result = await processor.process(chunk)

        # Verify tool call was detected
        tool_calls = result.metadata.get("tool_calls")
        assert tool_calls is not None, "Tool call should be detected from XML content"
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "read_file"

        # CRITICAL ASSERTION: finish_reason MUST be 'tool_calls'
        actual_finish_reason = result.metadata.get("finish_reason")
        assert actual_finish_reason == "tool_calls", (
            f"REGRESSION: finish_reason is '{actual_finish_reason}' but should be 'tool_calls'. "
            "Clients will not execute tool calls if finish_reason is not 'tool_calls'!"
        )

    @pytest.mark.asyncio
    async def test_wire_format_has_correct_finish_reason(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        Verify the SSE wire format contains correct finish_reason after processing.

        This tests the end-to-end flow: XML tool call -> detect -> serialize to SSE.
        """
        chunk = StreamingContent(
            content="""<execute_command>
<command>ls -la</command>
</execute_command>""",
            is_done=True,
            metadata={
                "session_id": "wire-format-test",
                "finish_reason": "stop",
                "id": "chatcmpl-wire-test",
                "model": "gemini-2.5-pro",
            },
        )

        result = await processor.process(chunk)

        # Verify the metadata was updated
        assert result.metadata.get("finish_reason") == "tool_calls"

        # Now serialize to SSE format and verify
        sse_bytes = result.to_bytes()
        sse_str = sse_bytes.decode("utf-8")

        # Parse the JSON from SSE format
        assert "data:" in sse_str
        # Extract JSON part (before [DONE])
        lines = [line for line in sse_str.split("\n") if line.startswith("data:")]
        json_line = lines[0].replace("data: ", "").strip()

        if json_line != "[DONE]":
            parsed = json.loads(json_line)

            # Check if choices exist and have finish_reason
            if parsed.get("choices"):
                wire_finish_reason = parsed["choices"][0].get("finish_reason")
                # The wire format should have tool_calls as finish_reason
                assert wire_finish_reason == "tool_calls", (
                    f"Wire format has finish_reason='{wire_finish_reason}' "
                    "but should be 'tool_calls'"
                )

    @pytest.mark.asyncio
    async def test_multi_chunk_gemini_streaming_with_stop(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        Test multi-chunk streaming where tool call XML is split and final chunk has stop.

        This simulates the real-world Gemini streaming behavior where:
        1. First chunks: partial tool call XML, no finish_reason
        2. Final chunk: completes the XML, has finish_reason: 'stop'
        3. Result: must have finish_reason: 'tool_calls'
        """
        session_id = "multi-chunk-gemini-test"

        # Chunk 1: Start of response and partial tool call
        chunk1 = StreamingContent(
            content="I will read the README file.\n\n<read_file>\n<path>README",
            is_done=False,
            metadata={
                "session_id": session_id,
                "id": "chatcmpl-chunk1",
            },
        )

        result1 = await processor.process(chunk1)
        # Should not have complete tool call yet
        tool_calls1 = result1.metadata.get("tool_calls")
        assert tool_calls1 is None or len(tool_calls1) == 0

        # Chunk 2: Complete the tool call with finish_reason: 'stop'
        chunk2 = StreamingContent(
            content=".md</path>\n</read_file>",
            is_done=True,
            metadata={
                "session_id": session_id,
                "id": "chatcmpl-chunk2",
                "finish_reason": "stop",  # Backend sends stop at the end
            },
        )

        result2 = await processor.process(chunk2)

        # Verify tool call was detected
        tool_calls2 = result2.metadata.get("tool_calls")
        assert tool_calls2 is not None, "Tool call should be detected after completion"
        assert len(tool_calls2) == 1
        assert tool_calls2[0]["function"]["name"] == "read_file"

        # CRITICAL: finish_reason must be tool_calls
        assert (
            result2.metadata.get("finish_reason") == "tool_calls"
        ), "Multi-chunk streaming must override finish_reason to 'tool_calls'"

    @pytest.mark.asyncio
    async def test_finish_reason_not_overridden_without_tool_call(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """
        Verify finish_reason is NOT modified when no tool call is detected.

        This ensures we only override finish_reason when there's actually a tool call.
        """
        chunk = StreamingContent(
            content="This is a normal response without any tool calls.",
            is_done=True,
            metadata={
                "session_id": "no-tool-call-test",
                "finish_reason": "stop",
            },
        )

        result = await processor.process(chunk)

        # No tool calls should be detected
        tool_calls = result.metadata.get("tool_calls")
        assert tool_calls is None or len(tool_calls) == 0

        # finish_reason should remain 'stop' (not modified)
        assert result.metadata.get("finish_reason") == "stop"
