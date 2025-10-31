import json
from collections.abc import AsyncGenerator  # Added import

import pytest
from pytest_mock import MockerFixture
from src.core.domain.streaming_content import StreamingContent
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.streaming_tool_call_repair_processor import (
    StreamingToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


@pytest.fixture
def repair_service() -> ToolCallRepairService:
    return ToolCallRepairService()


@pytest.fixture
def streaming_processor(
    repair_service: ToolCallRepairService,
) -> StreamingToolCallRepairProcessor:
    # Create an instance of ToolCallRepairProcessor to pass to StreamingToolCallRepairProcessor
    tool_call_processor = ToolCallRepairProcessor(repair_service)
    return StreamingToolCallRepairProcessor(tool_call_processor)


class TestToolCallRepairService:
    def test_repair_tool_calls_json_pattern(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = (
            '{"function_call": {"name": "test_func", "arguments": {"arg1": "val1"}}}'
        )
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired["function"]["name"] == "test_func"
        assert json.loads(repaired["function"]["arguments"]) == {"arg1": "val1"}

    def test_repair_tool_calls_text_pattern(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = 'TOOL CALL: test_func {"arg1": "val1"}'
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired["function"]["name"] == "test_func"
        assert json.loads(repaired["function"]["arguments"]) == {"arg1": "val1"}

    def test_repair_tool_calls_code_block_pattern(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = '```json\n{"tool": {"name": "test_func", "arguments": {"arg1": "val1"}}}\n```'
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired["function"]["name"] == "test_func"
        assert json.loads(repaired["function"]["arguments"]) == {"arg1": "val1"}

    def test_repair_tool_calls_xml_direct_tool(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <patch_file>
            <path>src/example.py</path>
            <patch_content>print("hello world")</patch_content>
        </patch_file>
        """
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired["function"]["name"] == "patch_file"
        arguments = json.loads(repaired["function"]["arguments"])
        assert arguments["path"] == "src/example.py"
        assert arguments["patch_content"] == 'print("hello world")'

    def test_repair_tool_calls_xml_use_mcp_wrapper(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <use_mcp_tool>
            <tool_name>patch_file</tool_name>
            <tool_arguments>
                <path>src/example.py</path>
                <patch_content>
                    print("updated")
                </patch_content>
            </tool_arguments>
        </use_mcp_tool>
        """
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired["function"]["name"] == "patch_file"
        arguments = json.loads(repaired["function"]["arguments"])
        assert arguments["path"] == "src/example.py"
        assert 'print("updated")' in arguments["patch_content"]

    def test_repair_tool_calls_no_match(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = "This is a regular message with no tool call."
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is None


class TestStreamingToolCallRepairProcessor:
    @pytest.mark.asyncio
    async def test_process_chunks_with_tool_call(
        self,
        streaming_processor: StreamingToolCallRepairProcessor,
        mocker: MockerFixture,
    ) -> None:
        from src.core.domain.streaming_response_processor import StreamingContent

        # Mock the underlying ToolCallRepairProcessor's process method
        # This is where the actual repair logic is now encapsulated
        mock_tool_call_repair_processor_process = mocker.AsyncMock(
            side_effect=[
                StreamingContent(content="Hello, "),
                StreamingContent(
                    content=json.dumps(
                        {
                            "id": "call_mock_id",
                            "type": "function",
                            "function": {
                                "name": "tool1",
                                "arguments": json.dumps({"param": "value"}),
                            },
                        }
                    )
                ),
                StreamingContent(content="World."),
                StreamingContent(content="", is_done=True),  # Final flush
            ]
        )
        mocker.patch.object(
            streaming_processor._tool_call_repair_processor,
            "process",
            new=mock_tool_call_repair_processor_process,
        )

        mock_chunks_data = [
            ProcessedResponse(content="Hello, "),
            ProcessedResponse(
                content='{"function_call": {"name": "tool1", "arguments": {"param": "value"}}}'
            ),  # This is the input to the processor, not its output
            ProcessedResponse(content="World."),
        ]

        async def mock_async_chunks_generator() -> (
            AsyncGenerator[ProcessedResponse, None]
        ):
            for item in mock_chunks_data:
                yield item

        mock_chunks = mocker.AsyncMock(side_effect=mock_async_chunks_generator)
        if hasattr(mock_chunks, "__aiter__") and hasattr(
            mock_chunks.__aiter__, "side_effect"
        ):
            mock_chunks.__aiter__.side_effect = mock_async_chunks_generator

        results: list[ProcessedResponse] = [
            pc
            async for pc in streaming_processor.process_chunks(
                mock_chunks, "test_session"
            )
        ]

        assert len(results) == 3
        assert results[0].content == "Hello, "
        assert results[1].content is not None
        repaired_tool_call = json.loads(results[1].content)
        assert repaired_tool_call["function"]["name"] == "tool1"
        assert json.loads(repaired_tool_call["function"]["arguments"]) == {
            "param": "value"
        }
        assert results[2].content == "World."

        # Verify calls to the ToolCallRepairProcessor's process method
        actual_calls = [
            c.args[0] for c in mock_tool_call_repair_processor_process.call_args_list
        ]

        assert len(actual_calls) == 4
        assert actual_calls[0].content == "Hello, "
        assert json.loads(actual_calls[1].content) == json.loads(
            mock_chunks_data[1].content
        )
        assert actual_calls[2].content == "World."
        assert actual_calls[3].is_done is True and actual_calls[3].content == ""

    @pytest.mark.asyncio
    async def test_process_chunks_with_xml_tool_call(
        self, streaming_processor: StreamingToolCallRepairProcessor
    ) -> None:
        input_chunks = [
            ProcessedResponse(content="<use_mcp_tool>"),
            ProcessedResponse(content="<tool_name>patch_file</tool_name>"),
            ProcessedResponse(
                content="""
                <tool_arguments>
                    <path>src/example.py</path>
                </tool_arguments>
                </use_mcp_tool>
                """
            ),
        ]

        async def generator() -> AsyncGenerator[ProcessedResponse, None]:
            for chunk in input_chunks:
                yield chunk

        results = [
            chunk
            async for chunk in streaming_processor.process_chunks(generator(), "sess")
        ]

        assert len(results) >= 1
        tool_chunks = [
            chunk for chunk in results if chunk.metadata.get("tool_calls")
        ]
        assert tool_chunks, "Expected at least one chunk with tool_calls metadata"
        chunk = tool_chunks[0]
        assert chunk.content == ""
        tool_calls = chunk.metadata.get("tool_calls")
        assert isinstance(tool_calls, list)
        assert tool_calls
        tool_call = tool_calls[0]
        assert tool_call["function"]["name"] == "patch_file"
        arguments = json.loads(tool_call["function"]["arguments"])
        assert arguments["path"] == "src/example.py"
        assert chunk.metadata.get("finish_reason") == "tool_calls"


class TestToolCallRepairProcessorBuffering:
    @pytest.mark.asyncio
    async def test_enforces_buffer_cap(self) -> None:
        service = ToolCallRepairService(max_buffer_bytes=12)
        processor = ToolCallRepairProcessor(service, max_buffer_bytes=12)

        # Create StreamingContent with same stream_id to simulate same stream
        stream_metadata = {"stream_id": "test_stream"}

        first = await processor.process(
            StreamingContent(content="A" * 8, metadata=stream_metadata)
        )
        assert first.content == ""

        second = await processor.process(
            StreamingContent(content="B" * 8, metadata=stream_metadata)
        )
        # Buffer is now 16 bytes, cap is 12, so 4 bytes should be flushed
        assert second.content == "AAAA"  # 4 bytes flushed to stay under 12 byte cap

        third = await processor.process(
            StreamingContent(content="C" * 4, metadata=stream_metadata)
        )
        # Buffer is now 16 bytes again (4 A + 8 B + 4 C), exceeds 12 by 4, so 4 A's flushed
        assert third.content == "AAAA"  # 4 remaining A's flushed

        final = await processor.process(
            StreamingContent(content="", is_done=True, metadata=stream_metadata)
        )
        # End of stream flushes remaining buffer
        assert final.content == "BBBBBBBBCCCC"  # Remaining 8 B's + 4 C's
