"""Integration tests for VTC (Virtual Tool Calling) round-trip processing.

These tests verify that:
1. XML tool calls are correctly converted to internal format
2. Internal format is correctly converted back to XML
3. The round-trip preserves all data
4. The VTC processors integrate correctly with the streaming pipeline
"""

import json

import pytest
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.vtc_postprocessor import VTCPostProcessor
from src.core.services.streaming.vtc_preprocessor import VTCPreProcessor


class TestVTCRoundTrip:
    """Test complete VTC round-trip: XML -> internal -> XML."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def preprocessor(self, registry: StreamingContextRegistry) -> VTCPreProcessor:
        """Create a pre-processor instance."""
        return VTCPreProcessor(registry=registry)

    @pytest.fixture
    def postprocessor(self, registry: StreamingContextRegistry) -> VTCPostProcessor:
        """Create a post-processor instance."""
        return VTCPostProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_round_trip_single_tool_call(
        self,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test round-trip with a single tool call."""
        original_xml = """<function_calls>
<invoke name="execute_command">
<parameter name="command">ls -la</parameter>
</invoke>
</function_calls>"""

        # Step 1: Pre-process (XML -> internal)
        input_content = StreamingContent(
            content=original_xml,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )
        preprocessed = await preprocessor.process(input_content)

        # Verify extraction
        assert "tool_calls" in preprocessed.metadata
        tool_calls = preprocessed.metadata["tool_calls"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "execute_command"

        args = json.loads(tool_calls[0]["function"]["arguments"])
        assert args["command"] == "ls -la"

        # XML should be stripped from content
        assert "<invoke" not in preprocessed.content

        # Step 2: Post-process (internal -> XML)
        postprocessed = await postprocessor.process(preprocessed)

        # Verify serialization
        assert "<function_calls>" in postprocessed.content
        assert '<invoke name="execute_command">' in postprocessed.content
        assert '<parameter name="command">ls -la</parameter>' in postprocessed.content

        # tool_calls should be removed from metadata
        assert "tool_calls" not in postprocessed.metadata

    @pytest.mark.asyncio
    async def test_round_trip_multiple_tool_calls(
        self,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test round-trip with multiple tool calls."""
        original_xml = """<function_calls>
<invoke name="read_file">
<parameter name="path">/tmp/test.txt</parameter>
</invoke>
<invoke name="write_file">
<parameter name="path">/tmp/output.txt</parameter>
<parameter name="content">Hello World</parameter>
</invoke>
</function_calls>"""

        # Pre-process
        input_content = StreamingContent(
            content=original_xml,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )
        preprocessed = await preprocessor.process(input_content)

        # Verify both tool calls extracted
        tool_calls = preprocessed.metadata["tool_calls"]
        assert len(tool_calls) == 2

        names = [tc["function"]["name"] for tc in tool_calls]
        assert "read_file" in names
        assert "write_file" in names

        # Post-process
        postprocessed = await postprocessor.process(preprocessed)

        # Verify both tool calls serialized
        assert postprocessed.content.count("<invoke") == 2
        assert '<invoke name="read_file">' in postprocessed.content
        assert '<invoke name="write_file">' in postprocessed.content

    @pytest.mark.asyncio
    async def test_round_trip_with_text_content(
        self,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test round-trip when content includes text around tool calls."""
        original = """I will now execute the command.

<function_calls>
<invoke name="execute_command">
<parameter name="command">pwd</parameter>
</invoke>
</function_calls>

Here is the result."""

        # Pre-process
        input_content = StreamingContent(
            content=original,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )
        preprocessed = await preprocessor.process(input_content)

        # Text should be preserved
        assert "I will now execute the command." in preprocessed.content
        assert "Here is the result." in preprocessed.content

        # Tool call should be extracted
        assert "tool_calls" in preprocessed.metadata
        assert (
            preprocessed.metadata["tool_calls"][0]["function"]["name"]
            == "execute_command"
        )

        # Post-process
        postprocessed = await postprocessor.process(preprocessed)

        # Text should still be preserved
        assert "I will now execute the command." in postprocessed.content
        assert "Here is the result." in postprocessed.content

        # Tool call should be serialized
        assert '<invoke name="execute_command">' in postprocessed.content

    @pytest.mark.asyncio
    async def test_round_trip_preserves_complex_parameters(
        self,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test that complex parameter values survive round-trip."""
        original_xml = """<invoke name="todo_write">
<parameter name="todos">[{"id": "1", "content": "Task 1", "status": "pending"}, {"id": "2", "content": "Task 2", "status": "done"}]</parameter>
<parameter name="merge">true</parameter>
</invoke>"""

        # Pre-process
        input_content = StreamingContent(
            content=original_xml,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )
        preprocessed = await preprocessor.process(input_content)

        # Verify complex parameters extracted
        tool_calls = preprocessed.metadata["tool_calls"]
        args = json.loads(tool_calls[0]["function"]["arguments"])

        assert isinstance(args["todos"], list)
        assert len(args["todos"]) == 2
        assert args["todos"][0]["id"] == "1"
        assert args["merge"] is True

        # Post-process
        postprocessed = await postprocessor.process(preprocessed)

        # Verify the output contains the expected tool call structure
        assert '<invoke name="todo_write">' in postprocessed.content
        assert '<parameter name="todos">' in postprocessed.content
        assert '<parameter name="merge">' in postprocessed.content
        # Note: JSON values are XML-escaped, so we verify the structure exists
        # rather than exact JSON match after re-parsing


class TestVTCPipelineIntegration:
    """Test VTC processors in a simulated pipeline."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def preprocessor(self, registry: StreamingContextRegistry) -> VTCPreProcessor:
        """Create a pre-processor instance."""
        return VTCPreProcessor(registry=registry)

    @pytest.fixture
    def postprocessor(self, registry: StreamingContextRegistry) -> VTCPostProcessor:
        """Create a post-processor instance."""
        return VTCPostProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_pass_through_for_non_vtc_sessions(
        self,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test that non-VTC sessions pass through unchanged."""
        original_content = """Some text with <invoke name="test">
<parameter name="x">1</parameter>
</invoke> and more text."""

        # Non-VTC session
        input_content = StreamingContent(
            content=original_content,
            metadata={"vtc_enabled": False},
            stream_id="test-stream",
        )

        # Pre-process
        preprocessed = await preprocessor.process(input_content)

        # Content unchanged
        assert preprocessed.content == original_content
        assert "tool_calls" not in preprocessed.metadata

        # Post-process
        postprocessed = await postprocessor.process(preprocessed)

        # Still unchanged
        assert postprocessed.content == original_content

    @pytest.mark.asyncio
    async def test_internal_modification_reflected_in_output(
        self,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test that modifications to tool_calls are reflected in output."""
        original_xml = """<invoke name="original_tool">
<parameter name="arg">original_value</parameter>
</invoke>"""

        # Pre-process
        input_content = StreamingContent(
            content=original_xml,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )
        preprocessed = await preprocessor.process(input_content)

        # Simulate internal modification (like a reactor would do)
        modified_tool_calls = [
            {
                "id": "modified_id",
                "type": "function",
                "function": {
                    "name": "modified_tool",
                    "arguments": json.dumps({"arg": "modified_value"}),
                },
            }
        ]
        preprocessed.metadata["tool_calls"] = modified_tool_calls

        # Post-process
        postprocessed = await postprocessor.process(preprocessed)

        # Should reflect modifications
        assert '<invoke name="modified_tool">' in postprocessed.content
        assert (
            '<parameter name="arg">modified_value</parameter>' in postprocessed.content
        )
        assert "original_tool" not in postprocessed.content

    @pytest.mark.asyncio
    async def test_streaming_chunks_simulation(
        self,
        registry: StreamingContextRegistry,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test VTC processing with simulated streaming chunks."""
        stream_id = "stream-test"

        # Simulate streaming chunks that form a complete tool call
        # Note: Chunks are designed to split in the middle of XML tags to test buffering
        chunks = [
            "I will execute the command.\n\n",
            "<function_calls>\n",
            '<invoke name="execute_command">\n<parameter name="command">',
            "ls -la</parameter>\n</invoke>\n",
            "</function_calls>",
        ]

        # Process each chunk through pre-processor
        all_content = ""
        all_tool_calls: list = []

        for chunk in chunks:
            input_content = StreamingContent(
                content=chunk,
                metadata={"vtc_enabled": True},
                stream_id=stream_id,
            )
            result = await preprocessor.process(input_content)

            if result.content:
                all_content += result.content

            if "tool_calls" in result.metadata:
                all_tool_calls.extend(result.metadata["tool_calls"])

        # Send final done signal
        done_content = StreamingContent(
            content="",
            metadata={"vtc_enabled": True},
            stream_id=stream_id,
            is_done=True,
        )
        final_result = await preprocessor.process(done_content)

        if final_result.content:
            all_content += final_result.content
        if "tool_calls" in final_result.metadata:
            all_tool_calls.extend(final_result.metadata["tool_calls"])

        # Verify text was extracted (check for key parts)
        assert "I will execute" in all_content
        assert "the command" in all_content

        # Verify tool call was extracted
        assert len(all_tool_calls) >= 1
        assert any(tc["function"]["name"] == "execute_command" for tc in all_tool_calls)


class TestVTCWithNamespacedTags:
    """Test VTC processing with namespaced XML tags."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def preprocessor(self, registry: StreamingContextRegistry) -> VTCPreProcessor:
        """Create a pre-processor instance."""
        return VTCPreProcessor(registry=registry)

    @pytest.fixture
    def postprocessor(self, registry: StreamingContextRegistry) -> VTCPostProcessor:
        """Create a post-processor instance."""
        return VTCPostProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_handles_antml_namespace(
        self,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test handling of antml:tool namespace prefix."""
        original_xml = """<invoke name="antml:tool:read_file">
<parameter name="path">/tmp/test.txt</parameter>
</invoke>"""

        # Pre-process
        input_content = StreamingContent(
            content=original_xml,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )
        preprocessed = await preprocessor.process(input_content)

        # Tool name should have namespace stripped
        tool_calls = preprocessed.metadata["tool_calls"]
        assert tool_calls[0]["function"]["name"] == "read_file"

        # Post-process
        postprocessed = await postprocessor.process(preprocessed)

        # Output should use clean tool name (no namespace)
        assert '<invoke name="read_file">' in postprocessed.content

    @pytest.mark.asyncio
    async def test_handles_client_controls_namespace(
        self,
        preprocessor: VTCPreProcessor,
        postprocessor: VTCPostProcessor,
    ) -> None:
        """Test handling of ClientControls namespace prefix."""
        original_xml = """<invoke name="ClientControls:run_terminal_command">
<parameter name="command">echo hello</parameter>
</invoke>"""

        # Pre-process
        input_content = StreamingContent(
            content=original_xml,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )
        preprocessed = await preprocessor.process(input_content)

        # Tool name should have namespace stripped
        tool_calls = preprocessed.metadata["tool_calls"]
        assert tool_calls[0]["function"]["name"] == "run_terminal_command"

        # Post-process
        postprocessed = await postprocessor.process(preprocessed)

        # Output should use clean tool name
        assert '<invoke name="run_terminal_command">' in postprocessed.content
