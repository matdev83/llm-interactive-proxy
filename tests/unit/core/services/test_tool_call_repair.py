import json
from collections.abc import AsyncGenerator  # Added import
from typing import Any  # Added import

import pytest
from pytest_mock import MockerFixture
from src.core.interfaces.response_processor_interface import ProcessedResponse
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
    return StreamingToolCallRepairProcessor(repair_service)


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

    def test_repair_tool_calls_no_match(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = "This is a regular message with no tool call."
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is None

    @pytest.mark.asyncio
    async def test_process_chunk_for_streaming_full_tool_call_in_one_chunk(
        self, repair_service: ToolCallRepairService
    ) -> None:
        session_id = "test_session_1"
        chunk_content = 'Hello, this is a message. {"function_call": {"name": "tool1", "arguments": {"param": "value"}}} More text.'

        results = [
            pc
            async for pc in repair_service.process_chunk_for_streaming(
                chunk_content, session_id, is_final_chunk=True
            )
        ]

        assert len(results) == 2
        assert results[0].content == "Hello, this is a message. "
        assert results[1].content is not None
        repaired_tool_call = json.loads(results[1].content)
        assert repaired_tool_call["function"]["name"] == "tool1"
        assert json.loads(repaired_tool_call["function"]["arguments"]) == {
            "param": "value"
        }

    @pytest.mark.asyncio
    async def test_process_chunk_for_streaming_tool_call_split_across_chunks(
        self, repair_service: ToolCallRepairService, mocker: MockerFixture
    ) -> None:
        session_id = "test_session_2"
        mock_chunks_data = [
            ProcessedResponse(
                content='This is the start. {"function_call": {"name": "tool2", "arguments": {"p'
            ),
            ProcessedResponse(content='aram": "value"}}} And the end.'),
        ]

        from collections.abc import AsyncGenerator

        async def mock_async_chunks_generator() -> (
            AsyncGenerator[ProcessedResponse, None]
        ):
            for item in mock_chunks_data:
                yield item

        mock_chunks = mocker.AsyncMock(side_effect=mock_async_chunks_generator)
        # Ensure async iteration yields from our generator in all environments
        if hasattr(mock_chunks, "__aiter__") and hasattr(
            mock_chunks.__aiter__, "side_effect"
        ):
            mock_chunks.__aiter__.side_effect = mock_async_chunks_generator

        results: list[ProcessedResponse] = []
        async for chunk in mock_chunks:
            async for processed_chunk in repair_service.process_chunk_for_streaming(
                chunk.content, session_id, is_final_chunk=False
            ):
                results.append(processed_chunk)

        # Final processing
        async for processed_chunk in repair_service.process_chunk_for_streaming(
            "", session_id, is_final_chunk=True
        ):
            results.append(processed_chunk)

        assert len(results) == 2
        assert results[0].content == "This is the start. "
        assert results[1].content is not None
        repaired_tool_call = json.loads(results[1].content)
        assert repaired_tool_call["function"]["name"] == "tool2"
        assert json.loads(repaired_tool_call["function"]["arguments"]) == {
            "param": "value"
        }


class TestStreamingToolCallRepairProcessor:
    @pytest.mark.asyncio
    async def test_process_chunks_delegates_to_repair_service(
        self,
        streaming_processor: StreamingToolCallRepairProcessor,
        repair_service: ToolCallRepairService,
        mocker: MockerFixture,
    ) -> None:
        async def mock_generator(  # type: ignore[no-untyped-def]
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[ProcessedResponse, None]:
            yield ProcessedResponse(content="processed chunk 1")
            yield ProcessedResponse(content="processed chunk 2")

        mock_process_chunk = mocker.AsyncMock(side_effect=mock_generator)
        mocker.patch.object(
            repair_service, "process_chunk_for_streaming", new=mock_process_chunk
        )

        mock_chunks_data = [
            ProcessedResponse(content="chunk A"),
            ProcessedResponse(content="chunk B"),
        ]

        async def mock_async_chunks_generator() -> (
            AsyncGenerator[ProcessedResponse, None]
        ):
            for item in mock_chunks_data:
                yield item

        mock_chunks = mocker.AsyncMock(side_effect=mock_async_chunks_generator)
        # Ensure async iteration yields from our generator
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

        assert len(results) == 4  # 2 from each mock_process_chunk call
        assert results[0].content == "processed chunk 1"
        assert results[1].content == "processed chunk 2"
        assert results[2].content == "processed chunk 1"
        assert results[3].content == "processed chunk 2"

        # Verify calls to process_chunk_for_streaming
        # Explicitly cast to Any to satisfy mypy's strictness with mocker.call types
        mock_process_chunk.assert_has_calls(
            [
                mocker.call("chunk A", "test_session", is_final_chunk=False),  # type: ignore
                mocker.call("chunk B", "test_session", is_final_chunk=False),  # type: ignore
                mocker.call("", "test_session", is_final_chunk=True),  # type: ignore
            ]
        )
