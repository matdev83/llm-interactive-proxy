"""Tests for hybrid connector response filtering functionality."""

import json

import pytest
from src.connectors.hybrid import HybridConnector
from src.core.config.app_config import AppConfig
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def hybrid_connector():
    """Create a hybrid connector instance for testing."""
    config = AppConfig()
    # We don't need full initialization for these unit tests
    connector = HybridConnector(
        client=None,  # type: ignore
        config=config,
        translation_service=None,  # type: ignore
        backend_registry=None,
    )
    return connector


class TestReasoningTagStripping:
    """Test reasoning tag stripping functionality."""

    def test_strip_thinking_tags(self, hybrid_connector):
        """Test stripping <thinking> tags."""
        content = "<thinking>This is reasoning</thinking>This is the answer"
        result = hybrid_connector._strip_reasoning_tags(content)
        assert result == "This is the answer"

    def test_strip_think_tags(self, hybrid_connector):
        """Test stripping <think> tags."""
        content = "<think>This is reasoning</think>This is the answer"
        result = hybrid_connector._strip_reasoning_tags(content)
        assert result == "This is the answer"

    def test_strip_reasoning_tags(self, hybrid_connector):
        """Test stripping <reasoning> tags."""
        content = "<reasoning>This is reasoning</reasoning>This is the answer"
        result = hybrid_connector._strip_reasoning_tags(content)
        assert result == "This is the answer"

    def test_strip_reason_tags(self, hybrid_connector):
        """Test stripping <reason> tags."""
        content = "<reason>This is reasoning</reason>This is the answer"
        result = hybrid_connector._strip_reasoning_tags(content)
        assert result == "This is the answer"

    def test_strip_multiple_tags(self, hybrid_connector):
        """Test stripping multiple reasoning tags."""
        content = (
            "<thinking>First reasoning</thinking>"
            "Some text"
            "<reasoning>Second reasoning</reasoning>"
            "Final answer"
        )
        result = hybrid_connector._strip_reasoning_tags(content)
        assert "First reasoning" not in result
        assert "Second reasoning" not in result
        assert "Some text" in result
        assert "Final answer" in result

    def test_strip_multiline_tags(self, hybrid_connector):
        """Test stripping tags with multiline content."""
        content = """<thinking>
This is
multiline
reasoning
</thinking>
This is the answer"""
        result = hybrid_connector._strip_reasoning_tags(content)
        assert "reasoning" not in result.lower() or result == "This is the answer"
        assert "This is the answer" in result

    def test_strip_case_insensitive(self, hybrid_connector):
        """Test case-insensitive tag stripping."""
        content = "<THINKING>Reasoning</THINKING>Answer"
        result = hybrid_connector._strip_reasoning_tags(content)
        assert "Reasoning" not in result
        assert "Answer" in result

    def test_strip_instruction_prefix(self, hybrid_connector):
        """Test stripping instruction prefix."""
        content = "Consider this reasoning when formulating your response:\n\n<thinking>Reasoning</thinking>\n\nAnswer"
        result = hybrid_connector._strip_reasoning_tags(content)
        assert "Consider this reasoning" not in result
        assert "Reasoning" not in result
        assert "Answer" in result

    def test_no_tags_present(self, hybrid_connector):
        """Test content without reasoning tags."""
        content = "This is just a normal answer"
        result = hybrid_connector._strip_reasoning_tags(content)
        assert result == content


class TestResponseContentFiltering:
    """Test response content filtering functionality."""

    def test_filter_sse_chunk_with_content(self, hybrid_connector):
        """Test filtering SSE chunk with content."""
        chunk_data = {
            "choices": [
                {"delta": {"content": "<thinking>Reasoning</thinking>Answer text"}}
            ]
        }
        sse_chunk = f"data: {json.dumps(chunk_data)}\n\n"

        result = hybrid_connector._filter_response_content(sse_chunk)

        # Parse the result
        assert result.startswith("data: ")
        data_part = result[6:].strip()
        parsed = json.loads(data_part)

        # Check that reasoning tags are removed
        content = parsed["choices"][0]["delta"]["content"]
        assert "<thinking>" not in content
        assert "Reasoning" not in content
        assert "Answer text" in content

    def test_filter_sse_chunk_with_tool_calls(self, hybrid_connector):
        """Test filtering tool calls in SSE chunks."""
        chunk_data = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "function": {
                                    "arguments": '<thinking>Reasoning</thinking>{"param": "value"}'
                                }
                            }
                        ]
                    }
                }
            ]
        }
        sse_chunk = f"data: {json.dumps(chunk_data)}\n\n"

        result = hybrid_connector._filter_response_content(sse_chunk)

        # Parse the result
        data_part = result[6:].strip()
        parsed = json.loads(data_part)

        # Check that reasoning tags are removed from tool call arguments
        arguments = parsed["choices"][0]["delta"]["tool_calls"][0]["function"][
            "arguments"
        ]
        assert "<thinking>" not in arguments
        assert "Reasoning" not in arguments
        assert '{"param": "value"}' in arguments

    def test_filter_message_with_tool_calls(self, hybrid_connector):
        """Test filtering tool calls in message."""
        chunk_data = {
            "choices": [
                {
                    "message": {
                        "content": "<thinking>Reasoning</thinking>Answer",
                        "tool_calls": [
                            {
                                "function": {
                                    "arguments": '<reasoning>Think</reasoning>{"key": "val"}'
                                }
                            }
                        ],
                    }
                }
            ]
        }
        sse_chunk = f"data: {json.dumps(chunk_data)}\n\n"

        result = hybrid_connector._filter_response_content(sse_chunk)

        # Parse the result
        data_part = result[6:].strip()
        parsed = json.loads(data_part)

        # Check content is filtered
        content = parsed["choices"][0]["message"]["content"]
        assert "<thinking>" not in content
        assert "Answer" in content

        # Check tool call arguments are filtered
        arguments = parsed["choices"][0]["message"]["tool_calls"][0]["function"][
            "arguments"
        ]
        assert "<reasoning>" not in arguments
        assert '{"key": "val"}' in arguments

    def test_filter_done_marker(self, hybrid_connector):
        """Test that [DONE] marker is not modified."""
        sse_chunk = "data: [DONE]\n\n"
        result = hybrid_connector._filter_response_content(sse_chunk)
        assert result == sse_chunk

    def test_filter_bytes_content(self, hybrid_connector):
        """Test filtering bytes content."""
        chunk_data = {
            "choices": [{"delta": {"content": "<thinking>Reasoning</thinking>Answer"}}]
        }
        sse_chunk = f"data: {json.dumps(chunk_data)}\n\n".encode()

        result = hybrid_connector._filter_response_content(sse_chunk)

        # Result should be bytes
        assert isinstance(result, bytes)

        # Parse the result
        result_str = result.decode("utf-8")
        data_part = result_str[6:].strip()
        parsed = json.loads(data_part)

        # Check filtering
        content = parsed["choices"][0]["delta"]["content"]
        assert "<thinking>" not in content
        assert "Answer" in content

    def test_filter_non_json_content(self, hybrid_connector):
        """Test filtering non-JSON content."""
        content = "data: <thinking>Reasoning</thinking>Plain text\n\n"
        result = hybrid_connector._filter_response_content(content)

        # Should strip tags from plain text
        assert "<thinking>" not in result
        assert "Plain text" in result

    def test_filter_dict_content_removes_reasoning(self, hybrid_connector):
        """Test filtering dict content removes reasoning payloads."""
        original = {
            "id": "123",
            "choices": [
                {
                    "delta": {
                        "reasoning_content": "<thinking>Plan</thinking>",
                        "content": "<thinking>Reasoning</thinking>Answer",
                        "tool_calls": [
                            {
                                "function": {
                                    "arguments": "<think>Prep</think>{}\n",
                                }
                            }
                        ],
                    }
                }
            ],
        }

        filtered = hybrid_connector._filter_response_content(original)

        assert filtered is not original
        delta = filtered["choices"][0]["delta"]
        assert "reasoning_content" not in delta
        assert delta["content"] == "Answer"
        arguments = delta["tool_calls"][0]["function"]["arguments"]
        assert "<think>" not in arguments
        assert "{}" in arguments


class TestStreamFiltering:
    """Test streaming response filtering."""

    @pytest.mark.asyncio
    async def test_filter_response_stream(self, hybrid_connector):
        """Test filtering a complete response stream."""

        # Create mock stream
        async def mock_stream():
            chunks = [
                ProcessedResponse(
                    content=f"data: {json.dumps({'choices': [{'delta': {'content': '<thinking>Reasoning</thinking>Part 1'}}]})}\n\n"
                ),
                ProcessedResponse(
                    content=f"data: {json.dumps({'choices': [{'delta': {'content': ' Part 2'}}]})}\n\n"
                ),
                ProcessedResponse(content="data: [DONE]\n\n"),
            ]
            for chunk in chunks:
                yield chunk

        # Create mock response
        mock_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
        )

        # Filter the stream
        filtered_response = await hybrid_connector._filter_response_stream(
            mock_response
        )

        # Collect filtered chunks
        filtered_chunks = []
        async for chunk in filtered_response.content:
            filtered_chunks.append(chunk.content)

        # Verify filtering
        assert len(filtered_chunks) == 3

        # First chunk should have reasoning removed
        first_data = filtered_chunks[0][6:].strip()
        first_parsed = json.loads(first_data)
        first_content = first_parsed["choices"][0]["delta"]["content"]
        assert "<thinking>" not in first_content
        assert "Reasoning" not in first_content
        assert "Part 1" in first_content

        # Second chunk should be unchanged (note: strip() removes leading space)
        second_data = filtered_chunks[1][6:].strip()
        second_parsed = json.loads(second_data)
        second_content = second_parsed["choices"][0]["delta"]["content"]
        assert "Part 2" in second_content

        # Third chunk should be [DONE]
        assert "[DONE]" in filtered_chunks[2]

    @pytest.mark.asyncio
    async def test_filter_empty_stream(self, hybrid_connector):
        """Test filtering an empty stream."""

        async def empty_stream():
            return
            yield  # Make it a generator

        mock_response = StreamingResponseEnvelope(
            content=empty_stream(),
            media_type="text/event-stream",
        )

        filtered_response = await hybrid_connector._filter_response_stream(
            mock_response
        )

        # Should handle empty stream gracefully
        chunks = []
        async for chunk in filtered_response.content:
            chunks.append(chunk)

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_filter_preserves_metadata(self, hybrid_connector):
        """Test that filtering preserves chunk metadata."""

        async def mock_stream():
            yield ProcessedResponse(
                content=f"data: {json.dumps({'choices': [{'delta': {'content': '<thinking>R</thinking>A'}}]})}\n\n",
                usage={"tokens": 10},
                metadata={"test": "value"},
            )

        mock_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
        )

        filtered_response = await hybrid_connector._filter_response_stream(
            mock_response
        )

        # Collect chunks
        async for chunk in filtered_response.content:
            # Verify metadata is preserved
            assert chunk.usage == {"tokens": 10}
            assert chunk.metadata == {"test": "value"}
            break  # Only check first chunk
