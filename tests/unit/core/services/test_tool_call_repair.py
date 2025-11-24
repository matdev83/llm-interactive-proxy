import json
from collections.abc import AsyncGenerator  # Added import

import pytest
from pytest_mock import MockerFixture
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StreamingContent
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

    def test_repair_tool_calls_xml_direct_tool_nested(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <patch_file>
            <args>
                <file>
                    <path>src/core/services/streaming/tool_call_repair_processor.py</path>
                    <diff>
                        <content><![CDATA[
<<<<<<< SEARCH
return old_line
=======
return new_line
>>>>>>> REPLACE
]]></content>
                    </diff>
                </file>
            </args>
        </patch_file>
        """
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired["function"]["name"] == "patch_file"
        arguments = json.loads(repaired["function"]["arguments"])
        assert arguments["path"] == (
            "src/core/services/streaming/tool_call_repair_processor.py"
        )
        assert "diff" in arguments
        assert "<<<<<<< SEARCH" in arguments["diff"]

    def test_repair_tool_calls_xml_direct_tool_unescaped_diff(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <patch_file>
            <path>src/module.py</path>
            <diff>--- a/src/module.py
+++ b/src/module.py
@@ -1 +1 @@
-old = 1
+new = 2
<<<<<<< SEARCH
print(x < y)
=======
print(x > y)
>>>>>>> REPLACE
</diff>
        </patch_file>
        """

        repaired = repair_service.repair_tool_calls(content)

        assert repaired is not None
        assert repaired["function"]["name"] == "patch_file"
        args = json.loads(repaired["function"]["arguments"])
        assert args["path"] == "src/module.py"
        assert "new = 2" in args["diff"]
        assert "print(x < y)" in args["diff"]

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

    def test_repair_tool_calls_xml_with_prefix_text(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        I'll use the patch-file tool now.
        <patch_file>
            <path>src/example.py</path>
            <patch_content>print("hello world")</patch_content>
        </patch_file>
        """
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired["function"]["name"] == "patch_file"

    def test_repair_tool_calls_no_match(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = "This is a regular message with no tool call."
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is None

    def test_repair_tool_calls_in_messages_empty_list(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that empty message list returns empty list."""
        messages: list[dict[str, str]] = []
        repaired = repair_service.repair_tool_calls_in_messages(messages)
        assert repaired == []

    def test_repair_tool_calls_in_messages_no_assistant_messages(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that non-assistant messages are passed through unchanged."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "You are a helpful assistant"},
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)
        assert len(repaired) == 2
        assert repaired[0] == messages[0]
        assert repaired[1] == messages[1]

    def test_repair_tool_calls_in_messages_processes_last_assistant(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that only the last assistant message is processed."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "old_func", "arguments": {}}}',
            },
            {"role": "user", "content": "Continue"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "new_func", "arguments": {}}}',
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 4
        # First assistant message should not have tool_calls added
        assert "tool_calls" not in repaired[1]
        # Last assistant message should have tool_calls added
        assert "tool_calls" in repaired[3]
        assert repaired[3]["tool_calls"][0]["function"]["name"] == "new_func"

    def test_repair_tool_calls_in_messages_skips_processed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that messages with processing marker are skipped."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "test_func", "arguments": {}}}',
                "_tool_calls_processed": True,
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 2
        # Message should be unchanged (no new tool_calls added)
        assert repaired[1] == messages[1]

    def test_repair_tool_calls_in_messages_force_reprocess(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that force_reprocess bypasses processing marker."""
        messages = [
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "test_func", "arguments": {}}}',
                "_tool_calls_processed": True,
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(
            messages, force_reprocess=True
        )

        assert len(repaired) == 1
        # Tool calls should be added even though marker was present
        assert "tool_calls" in repaired[0]
        assert repaired[0]["tool_calls"][0]["function"]["name"] == "test_func"

    def test_repair_tool_calls_in_messages_marks_processed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that processed messages are marked with processing marker."""
        messages = [
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "test_func", "arguments": {}}}',
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 1
        # Message should be marked as processed
        assert repaired[0].get("_tool_calls_processed") is True

    def test_repair_tool_calls_in_messages_no_tool_calls_found(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that messages without tool calls are still marked as processed."""
        messages = [
            {"role": "assistant", "content": "This is a regular response."},
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 1
        # Message should be marked as processed even if no tool calls found
        assert repaired[0].get("_tool_calls_processed") is True
        # No tool_calls should be added
        assert "tool_calls" not in repaired[0]

    def test_repair_tool_calls_in_messages_multiple_assistant_messages(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test processing with multiple assistant messages in history."""
        messages = [
            {"role": "user", "content": "First question"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "func1", "arguments": {}}}',
            },
            {"role": "user", "content": "Second question"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "func2", "arguments": {}}}',
            },
            {"role": "user", "content": "Third question"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "func3", "arguments": {}}}',
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 6
        # Only the last assistant message should have tool_calls
        assert "tool_calls" not in repaired[1]
        assert "tool_calls" not in repaired[3]
        assert "tool_calls" in repaired[5]
        assert repaired[5]["tool_calls"][0]["function"]["name"] == "func3"

    def test_repair_tool_calls_in_messages_xml_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that XML tool calls are properly repaired in messages."""
        messages = [
            {
                "role": "assistant",
                "content": """
                <patch_file>
                    <path>src/example.py</path>
                    <patch_content>print("hello")</patch_content>
                </patch_file>
                """,
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 1
        assert "tool_calls" in repaired[0]
        assert repaired[0]["tool_calls"][0]["function"]["name"] == "patch_file"
        arguments = json.loads(repaired[0]["tool_calls"][0]["function"]["arguments"])
        assert arguments["path"] == "src/example.py"

    def test_repair_tool_calls_in_messages_preserves_existing_tool_calls(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that existing tool_calls in message are preserved."""
        existing_tool_call = {
            "id": "call_existing",
            "type": "function",
            "function": {"name": "existing_func", "arguments": "{}"},
        }
        messages = [
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "new_func", "arguments": {}}}',
                "tool_calls": [existing_tool_call],
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 1
        assert "tool_calls" in repaired[0]
        # Should have both existing and new tool call
        assert len(repaired[0]["tool_calls"]) == 2
        assert repaired[0]["tool_calls"][0] == existing_tool_call
        assert repaired[0]["tool_calls"][1]["function"]["name"] == "new_func"

    def test_repair_tool_calls_in_messages_with_object_messages(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test backward compatibility with object-based messages."""

        class Message:
            def __init__(self, role: str, content: str) -> None:
                self.role = role
                self.content = content

        messages = [
            Message("user", "Hello"),
            Message(
                "assistant",
                '{"function_call": {"name": "test_func", "arguments": {}}}',
            ),
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 2
        # First message should be unchanged
        assert repaired[0].role == "user"
        # Second message should have tool_calls added
        assert hasattr(repaired[1], "tool_calls")
        assert len(repaired[1].tool_calls) == 1
        assert repaired[1].tool_calls[0]["function"]["name"] == "test_func"
        # Should be marked as processed
        assert getattr(repaired[1], "_tool_calls_processed", False) is True

    def test_repair_tool_calls_in_messages_with_mixed_formats(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test handling of mixed dict and object message formats."""

        class Message:
            def __init__(self, role: str, content: str) -> None:
                self.role = role
                self.content = content

        messages: list[dict[str, str] | Message] = [
            {"role": "user", "content": "Hello"},
            Message(
                "assistant",
                '{"function_call": {"name": "func1", "arguments": {}}}',
            ),
            {"role": "user", "content": "Continue"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "func2", "arguments": {}}}',
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 4
        # Only last assistant message should have tool_calls
        assert (
            not hasattr(repaired[1], "tool_calls") or len(repaired[1].tool_calls) == 0
        )
        assert "tool_calls" in repaired[3]
        assert repaired[3]["tool_calls"][0]["function"]["name"] == "func2"

    def test_repair_tool_calls_in_messages_integration_large_conversation(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Integration test: Large conversation with multiple tool calls."""
        messages = []
        # Simulate a conversation with 20 turns
        for i in range(20):
            messages.append({"role": "user", "content": f"Question {i}"})
            messages.append(
                {
                    "role": "assistant",
                    "content": f'{{"function_call": {{"name": "func_{i}", "arguments": {{"turn": {i}}}}}}}',
                }
            )

        # First pass: process all messages
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 40
        # Only the last assistant message should have tool_calls
        for i in range(1, 40, 2):  # All assistant messages
            if i == 39:  # Last assistant message
                assert "tool_calls" in repaired[i]
                assert repaired[i]["tool_calls"][0]["function"]["name"] == "func_19"
                # Only the last assistant message should be marked as processed
                assert repaired[i].get("_tool_calls_processed") is True
            else:
                # Historical messages are skipped, not marked as processed
                assert "tool_calls" not in repaired[i]
                assert repaired[i].get("_tool_calls_processed") is None

        # Second pass: add new messages and process again
        repaired.append({"role": "user", "content": "Question 20"})
        repaired.append(
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "func_20", "arguments": {"turn": 20}}}',
            }
        )

        repaired_again = repair_service.repair_tool_calls_in_messages(repaired)

        assert len(repaired_again) == 42
        # Historical messages should be skipped
        for i in range(1, 40, 2):
            if i == 39:
                # This was processed in first pass, should be skipped due to marker
                assert "tool_calls" in repaired_again[i]
                assert repaired_again[i].get("_tool_calls_processed") is True
            else:
                # These were not processed in first pass, should still not have tool_calls
                assert "tool_calls" not in repaired_again[i]

        # New message should be processed
        assert "tool_calls" in repaired_again[41]
        assert repaired_again[41]["tool_calls"][0]["function"]["name"] == "func_20"
        assert repaired_again[41].get("_tool_calls_processed") is True

    def test_repair_tool_calls_in_messages_integration_with_errors(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Integration test: Messages with malformed tool calls."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "valid_func", "arguments": {}}}',
            },
            {"role": "user", "content": "Continue"},
            {
                "role": "assistant",
                "content": '{"function_call": {invalid json',  # Malformed JSON
            },
            {"role": "user", "content": "Try again"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "another_func", "arguments": {}}}',
            },
        ]

        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 6
        # Only last assistant message should be processed
        assert "tool_calls" not in repaired[1]
        assert "tool_calls" not in repaired[3]  # Malformed, no tool_calls added
        assert "tool_calls" in repaired[5]
        assert repaired[5]["tool_calls"][0]["function"]["name"] == "another_func"

    def test_repair_tool_calls_in_messages_force_reprocess_all(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test force_reprocess processes all messages regardless of markers."""
        messages = [
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "func1", "arguments": {}}}',
                "_tool_calls_processed": True,
            },
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "func2", "arguments": {}}}',
                "_tool_calls_processed": True,
            },
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "func3", "arguments": {}}}',
            },
        ]

        repaired = repair_service.repair_tool_calls_in_messages(
            messages, force_reprocess=True
        )

        assert len(repaired) == 3
        # All messages should have tool_calls added
        assert "tool_calls" in repaired[0]
        assert repaired[0]["tool_calls"][0]["function"]["name"] == "func1"
        assert "tool_calls" in repaired[1]
        assert repaired[1]["tool_calls"][0]["function"]["name"] == "func2"
        assert "tool_calls" in repaired[2]
        assert repaired[2]["tool_calls"][0]["function"]["name"] == "func3"

    def test_repair_tool_calls_in_messages_empty_content(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test handling of messages with empty or None content."""
        messages = [
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": None},
            {"role": "assistant"},  # No content key
        ]

        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 3
        # Only the last message should be processed (no tool_calls added due to empty content)
        assert "tool_calls" not in repaired[0]
        assert "tool_calls" not in repaired[1]
        assert "tool_calls" not in repaired[2]
        # Only the last assistant message should be marked as processed
        assert repaired[0].get("_tool_calls_processed") is None
        assert repaired[1].get("_tool_calls_processed") is None
        assert repaired[2].get("_tool_calls_processed") is True

    def test_repair_tool_calls_in_messages_preserves_message_structure(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that message structure and metadata are preserved."""
        messages = [
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "test_func", "arguments": {}}}',
                "metadata": {"custom": "data"},
                "timestamp": 123456789,
            },
        ]

        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 1
        # Original fields should be preserved
        assert repaired[0]["metadata"] == {"custom": "data"}
        assert repaired[0]["timestamp"] == 123456789
        # New fields should be added
        assert "tool_calls" in repaired[0]
        assert repaired[0].get("_tool_calls_processed") is True


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
        assert isinstance(results[1].content, str)
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
        chunk_payload = actual_calls[1].content
        assert isinstance(chunk_payload, str)
        assert isinstance(mock_chunks_data[1].content, str)
        assert json.loads(chunk_payload) == json.loads(mock_chunks_data[1].content)
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
        tool_chunks = [chunk for chunk in results if chunk.metadata.get("tool_calls")]
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

    @pytest.mark.asyncio
    async def test_skips_already_processed_chunks(
        self, streaming_processor: StreamingToolCallRepairProcessor
    ) -> None:
        """Test that streaming processor skips chunks marked as already processed."""
        from src.core.utils.message_processing_utils import (
            is_message_processed,
            mark_message_processed,
        )

        # Create chunks with tool calls so they emit immediately
        chunk1 = ProcessedResponse(
            content="Processing...",
            metadata={"tool_calls": [{"id": "call_1", "type": "function"}]},
        )
        chunk2 = ProcessedResponse(
            content="Already done",
            metadata={"tool_calls": [{"id": "call_2", "type": "function"}]},
        )
        mark_message_processed(chunk2)  # Mark second chunk as processed

        input_chunks = [chunk1, chunk2]

        async def generator() -> AsyncGenerator[ProcessedResponse, None]:
            for chunk in input_chunks:
                yield chunk

        results = [
            chunk
            async for chunk in streaming_processor.process_chunks(generator(), "sess")
        ]

        # Should get the processed chunk passed through
        processed_results = [r for r in results if is_message_processed(r)]
        assert len(processed_results) >= 1
        # Verify the processed chunk was passed through with its marker intact
        assert any(is_message_processed(r) for r in results)

    @pytest.mark.asyncio
    async def test_marks_final_message_as_processed(
        self,
        streaming_processor: StreamingToolCallRepairProcessor,
        mocker: MockerFixture,
    ) -> None:
        """Test that the final assembled message is marked as processed."""
        from src.core.domain.streaming_response_processor import StreamingContent
        from src.core.utils.message_processing_utils import is_message_processed

        # Mock the underlying processor to control what gets emitted
        mock_process = mocker.AsyncMock(
            side_effect=[
                StreamingContent(content="Hello "),
                StreamingContent(content="World"),
                StreamingContent(
                    content="",
                    is_done=True,
                    metadata={"tool_calls": [{"id": "call_1", "type": "function"}]},
                ),  # Final flush with tool call
            ]
        )
        mocker.patch.object(
            streaming_processor._tool_call_repair_processor,
            "process",
            new=mock_process,
        )

        input_chunks = [
            ProcessedResponse(content="Hello "),
            ProcessedResponse(content="World"),
        ]

        async def generator() -> AsyncGenerator[ProcessedResponse, None]:
            for chunk in input_chunks:
                yield chunk

        results = [
            chunk
            async for chunk in streaming_processor.process_chunks(generator(), "sess")
        ]

        # Should have results including the final flush
        assert len(results) >= 1

        # The final result (with tool calls) should be marked as processed
        final_results_with_tool_calls = [
            r for r in results if r.metadata.get("tool_calls")
        ]
        assert len(final_results_with_tool_calls) > 0
        assert is_message_processed(final_results_with_tool_calls[-1])

    @pytest.mark.asyncio
    async def test_performance_with_many_chunks(
        self, streaming_processor: StreamingToolCallRepairProcessor
    ) -> None:
        """Test that streaming processor handles many chunks efficiently without degradation."""
        import time

        # Create chunks with tool calls to ensure they're processed
        num_chunks = 50
        input_chunks = []
        for i in range(num_chunks):
            input_chunks.append(
                ProcessedResponse(
                    content=f"Text before tool {i}. ",
                    metadata={},
                )
            )

        async def generator() -> AsyncGenerator[ProcessedResponse, None]:
            for chunk in input_chunks:
                yield chunk

        start_time = time.time()
        _ = [
            chunk
            async for chunk in streaming_processor.process_chunks(generator(), "sess")
        ]
        elapsed_time = time.time() - start_time

        # Should complete quickly (under 1 second for 50 chunks)
        assert elapsed_time < 1.0, f"Processing took {elapsed_time}s, expected < 1s"

        # Should have processed the chunks (may be buffered and emitted as final)
        # The key is that it completes without hanging or performance issues
        assert True  # If we got here, performance is acceptable

    @pytest.mark.asyncio
    async def test_all_processed_chunks_skipped(
        self, streaming_processor: StreamingToolCallRepairProcessor
    ) -> None:
        """Test that when all chunks are already processed, they're all passed through."""
        from src.core.utils.message_processing_utils import mark_message_processed

        # Create chunks and mark all as processed
        chunk1 = ProcessedResponse(content="Hello, ")
        chunk2 = ProcessedResponse(content="World!")
        mark_message_processed(chunk1)
        mark_message_processed(chunk2)

        input_chunks = [chunk1, chunk2]

        async def generator() -> AsyncGenerator[ProcessedResponse, None]:
            for chunk in input_chunks:
                yield chunk

        results = [
            chunk
            async for chunk in streaming_processor.process_chunks(generator(), "sess")
        ]

        # Should get both chunks passed through
        assert len(results) == 2
        assert results[0].content == "Hello, "
        assert results[1].content == "World!"


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


class TestToolCallRepairProcessorReasoning:
    @pytest.mark.asyncio
    async def test_detects_tool_call_in_reasoning(
        self, repair_service: ToolCallRepairService
    ) -> None:
        processor = ToolCallRepairProcessor(repair_service)
        stream_id = "reasoning-stream"
        chunk = StreamingContent(
            content="",
            metadata={
                "stream_id": stream_id,
                "reasoning_content": """
                <patch_file>
                    <path>src/example.py</path>
                    <patch_content>print("hello")</patch_content>
                </patch_file>
                """,
            },
        )

        result = await processor.process(chunk)

        tool_calls = result.metadata.get("tool_calls")
        assert isinstance(tool_calls, list) and len(tool_calls) == 1
        call = tool_calls[0]
        assert call["function"]["name"] == "patch_file"
        args = json.loads(call["function"]["arguments"])
        assert args["path"] == "src/example.py"
        assert args["patch_content"] == 'print("hello")'
        assert result.content == ""
        assert "reasoning_content" not in result.metadata

    @pytest.mark.asyncio
    async def test_detects_tool_call_split_across_reasoning_chunks(
        self, repair_service: ToolCallRepairService
    ) -> None:
        processor = ToolCallRepairProcessor(repair_service)
        stream_id = "split-reasoning"

        first_chunk = StreamingContent(
            content="",
            metadata={
                "stream_id": stream_id,
                "reasoning_content": "<patch_file><path>src/app.py</path>",
            },
        )
        second_chunk = StreamingContent(
            content="",
            metadata={
                "stream_id": stream_id,
                "reasoning_content": "<patch_content>diff</patch_content></patch_file>",
            },
        )

        result1 = await processor.process(first_chunk)
        assert "tool_calls" not in result1.metadata
        assert result1.content == ""

        result2 = await processor.process(second_chunk)
        tool_calls = result2.metadata.get("tool_calls")
        assert isinstance(tool_calls, list) and len(tool_calls) == 1
        call = tool_calls[0]
        assert call["function"]["name"] == "patch_file"
        args = json.loads(call["function"]["arguments"])
        assert args["path"] == "src/app.py"
        assert args["patch_content"] == "diff"
        assert result2.content == ""
        assert "reasoning_content" not in result2.metadata
