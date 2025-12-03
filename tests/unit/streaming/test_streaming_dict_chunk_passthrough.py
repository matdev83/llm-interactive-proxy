"""
Tests for streaming dict chunk passthrough through middleware.

These tests verify that structured OpenAI-format chunks (dicts with "choices")
and StopChunkWithUsage objects pass through the streaming middleware correctly
without being converted to text or corrupted.
"""

from __future__ import annotations

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.ports.streaming_contracts import StopChunkWithUsage


class TestJSONRepairProcessorDictPassthrough:
    """Test that JSONRepairProcessor passes through structured dict chunks."""

    @pytest.fixture
    def json_repair_processor(self):
        """Create a JSONRepairProcessor instance."""
        from src.core.services.json_repair_service import JsonRepairService
        from src.core.services.streaming.json_repair_processor import (
            JsonRepairProcessor,
        )

        service = JsonRepairService()
        return JsonRepairProcessor(
            repair_service=service,
            buffer_cap_bytes=65536,
            strict_mode=False,
            enabled=True,
        )

    @pytest.mark.asyncio
    async def test_passthrough_openai_format_chunk_with_choices(
        self, json_repair_processor
    ):
        """OpenAI-format chunks with 'choices' should pass through unchanged."""
        chunk_content = {
            "id": "chatcmpl-test123",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello world"},
                    "finish_reason": None,
                }
            ],
        }

        input_chunk = StreamingContent(
            content=chunk_content,
            metadata={"model": "gemini-2.5-flash"},
            is_done=False,
        )

        result = await json_repair_processor.process(input_chunk)

        # Content should be unchanged (same dict, not converted to string)
        assert isinstance(result.content, dict), "Content should remain a dict"
        assert result.content == chunk_content, "Content should be unchanged"
        assert result.content["choices"][0]["delta"]["content"] == "Hello world"

    @pytest.mark.asyncio
    async def test_passthrough_openai_format_chunk_with_usage(
        self, json_repair_processor
    ):
        """OpenAI-format chunks with 'usage' should pass through unchanged."""
        chunk_content = {
            "id": "chatcmpl-test123",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-flash",
            "choices": [],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

        input_chunk = StreamingContent(
            content=chunk_content,
            metadata={},
            is_done=True,
        )

        result = await json_repair_processor.process(input_chunk)

        assert isinstance(result.content, dict), "Content should remain a dict"
        assert result.content["usage"]["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_passthrough_stop_chunk_with_usage(self, json_repair_processor):
        """StopChunkWithUsage should pass through unchanged."""
        chunk_data = {
            "id": "chatcmpl-stop123",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "4"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 1,
                "total_tokens": 16,
            },
        }
        stop_chunk = StopChunkWithUsage(chunk_data)

        input_chunk = StreamingContent(
            content=stop_chunk,
            metadata={"finish_reason": "stop"},
            is_done=True,
        )

        result = await json_repair_processor.process(input_chunk)

        # Content should be the exact same StopChunkWithUsage instance
        assert isinstance(
            result.content, StopChunkWithUsage
        ), "Should preserve StopChunkWithUsage type"
        assert result.content is stop_chunk, "Should be the exact same instance"
        assert result.content["choices"][0]["delta"]["content"] == "4"

    @pytest.mark.asyncio
    async def test_text_content_still_processed(self, json_repair_processor):
        """Regular text content should still go through JSON repair."""
        # Text with broken JSON that should be repaired
        input_chunk = StreamingContent(
            content='Some text before {"key": "value"} and after',
            metadata={},
            is_done=False,
        )

        result = await json_repair_processor.process(input_chunk)

        # Text content should be processed (not passed through unchanged)
        assert isinstance(result.content, str), "Text content should remain string"

    @pytest.mark.asyncio
    async def test_empty_choices_with_usage_passthrough(self, json_repair_processor):
        """Chunk with empty choices but usage data should pass through."""
        chunk_content = {
            "id": "chatcmpl-usage-only",
            "object": "chat.completion.chunk",
            "choices": [],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        }

        input_chunk = StreamingContent(
            content=chunk_content,
            metadata={},
            is_done=True,
        )

        result = await json_repair_processor.process(input_chunk)

        assert isinstance(result.content, dict)
        assert result.content["usage"]["total_tokens"] == 30


class TestEditPrecisionMiddlewareDictHandling:
    """Test that EditPrecisionResponseMiddleware handles dict content properly."""

    @pytest.fixture
    def mock_app_state(self):
        """Create a mock application state."""
        from unittest.mock import MagicMock

        app_state = MagicMock()
        app_state.get_setting.return_value = {}
        return app_state

    @pytest.fixture
    def edit_precision_middleware(self, mock_app_state):
        """Create an EditPrecisionResponseMiddleware instance."""
        from src.core.services.edit_precision_response_middleware import (
            EditPrecisionResponseMiddleware,
        )

        return EditPrecisionResponseMiddleware(app_state=mock_app_state)

    @pytest.mark.asyncio
    async def test_extract_text_from_chunk_with_content(
        self, edit_precision_middleware
    ):
        """Should extract text from OpenAI-format chunk delta.content."""
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello world"},
                    "finish_reason": None,
                }
            ]
        }

        text = edit_precision_middleware._extract_text_from_chunk(chunk)
        assert text == "Hello world"

    @pytest.mark.asyncio
    async def test_extract_text_from_chunk_empty_delta(self, edit_precision_middleware):
        """Should return empty string for chunk with empty delta."""
        chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}

        text = edit_precision_middleware._extract_text_from_chunk(chunk)
        assert text == ""

    @pytest.mark.asyncio
    async def test_extract_text_from_chunk_no_choices(self, edit_precision_middleware):
        """Should return empty string for chunk without choices."""
        chunk = {"id": "test", "usage": {"total_tokens": 10}}

        text = edit_precision_middleware._extract_text_from_chunk(chunk)
        assert text == ""

    @pytest.mark.asyncio
    async def test_extract_text_from_message_format(self, edit_precision_middleware):
        """Should extract text from message format (non-streaming)."""
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Response text"},
                    "finish_reason": "stop",
                }
            ]
        }

        text = edit_precision_middleware._extract_text_from_chunk(chunk)
        assert text == "Response text"

    @pytest.mark.asyncio
    async def test_process_dict_content_passthrough(
        self, edit_precision_middleware, mock_app_state
    ):
        """Dict content should pass through without TypeError."""
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        chunk_content = {
            "id": "chatcmpl-test",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "Test content"},
                    "finish_reason": None,
                }
            ],
        }

        response = ProcessedResponse(
            content=chunk_content,
            metadata={"model": "test-model"},
        )

        # Should not raise TypeError
        result = await edit_precision_middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=True,
        )

        # Result should be returned (not raise exception)
        assert result is not None

    @pytest.mark.asyncio
    async def test_process_stop_chunk_with_usage(
        self, edit_precision_middleware, mock_app_state
    ):
        """StopChunkWithUsage content should pass through without TypeError."""
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        stop_chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-stop",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "4"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 1,
                    "total_tokens": 11,
                },
            }
        )

        response = ProcessedResponse(
            content=stop_chunk,
            metadata={"finish_reason": "stop"},
        )

        # Should not raise TypeError (the original bug)
        result = await edit_precision_middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=True,
        )

        assert result is not None


class TestStreamingMiddlewareChainIntegration:
    """Integration tests for dict content flowing through multiple middleware."""

    @pytest.mark.asyncio
    async def test_stop_chunk_flows_through_json_repair_and_normalize(self):
        """StopChunkWithUsage should flow through JSONRepairProcessor correctly."""
        from src.core.services.json_repair_service import JsonRepairService
        from src.core.services.streaming.json_repair_processor import (
            JsonRepairProcessor,
        )

        service = JsonRepairService()
        processor = JsonRepairProcessor(
            repair_service=service,
            buffer_cap_bytes=65536,
            strict_mode=False,
            enabled=True,
        )

        # Create a StopChunkWithUsage like the connector yields
        stop_chunk_data = {
            "id": "chatcmpl-realworld",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "The answer is 4"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 4,
                "total_tokens": 19,
            },
        }
        stop_chunk = StopChunkWithUsage(stop_chunk_data)

        input_content = StreamingContent(
            content=stop_chunk,
            metadata={"finish_reason": "stop", "model": "gemini-2.5-flash"},
            is_done=True,
            usage=stop_chunk_data["usage"],
        )

        # Process through JSONRepairProcessor
        result = await processor.process(input_content)

        # Verify the chunk is preserved correctly
        assert isinstance(result.content, StopChunkWithUsage)
        assert result.content["choices"][0]["delta"]["content"] == "The answer is 4"
        assert result.content["usage"]["total_tokens"] == 19
        assert result.is_done is True

    @pytest.mark.asyncio
    async def test_regular_content_chunk_flows_through_processors(self):
        """Regular content chunks should flow through without modification."""
        from src.core.services.json_repair_service import JsonRepairService
        from src.core.services.streaming.json_repair_processor import (
            JsonRepairProcessor,
        )

        service = JsonRepairService()
        processor = JsonRepairProcessor(
            repair_service=service,
            buffer_cap_bytes=65536,
            strict_mode=False,
            enabled=True,
        )

        content_chunk = {
            "id": "chatcmpl-content",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello, "},
                    "finish_reason": None,
                }
            ],
        }

        input_content = StreamingContent(
            content=content_chunk,
            metadata={"model": "gemini-2.5-flash"},
            is_done=False,
        )

        result = await processor.process(input_content)

        # Should be passed through unchanged
        assert isinstance(result.content, dict)
        assert result.content["choices"][0]["delta"]["content"] == "Hello, "
        assert result.is_done is False


class TestNormalizeChunkTextSafety:
    """Test that _normalize_chunk_text handles edge cases safely."""

    @pytest.fixture
    def json_repair_processor(self):
        """Create a JSONRepairProcessor instance."""
        from src.core.services.json_repair_service import JsonRepairService
        from src.core.services.streaming.json_repair_processor import (
            JsonRepairProcessor,
        )

        service = JsonRepairService()
        return JsonRepairProcessor(
            repair_service=service,
            buffer_cap_bytes=65536,
            strict_mode=False,
            enabled=True,
        )

    def test_normalize_stop_chunk_with_usage_to_json(self, json_repair_processor):
        """StopChunkWithUsage should be converted to JSON safely."""
        stop_chunk = StopChunkWithUsage(
            {"id": "test", "choices": [], "usage": {"total_tokens": 10}}
        )

        # This should NOT raise TypeError or UsageChunkLeakError
        result = json_repair_processor._normalize_chunk_text(stop_chunk)

        assert isinstance(result, str)
        assert '"id": "test"' in result
        assert '"total_tokens": 10' in result

    def test_normalize_regular_dict(self, json_repair_processor):
        """Regular dicts should be converted to JSON."""
        chunk = {"key": "value", "nested": {"inner": 123}}

        result = json_repair_processor._normalize_chunk_text(chunk)

        assert isinstance(result, str)
        assert '"key": "value"' in result

    def test_normalize_string_passthrough(self, json_repair_processor):
        """Strings should pass through unchanged."""
        text = "Hello world"

        result = json_repair_processor._normalize_chunk_text(text)

        assert result == text

    def test_normalize_bytes(self, json_repair_processor):
        """Bytes should be decoded to string."""
        data = b"Hello bytes"

        result = json_repair_processor._normalize_chunk_text(data)

        assert result == "Hello bytes"

    def test_normalize_none(self, json_repair_processor):
        """None should return empty string."""
        result = json_repair_processor._normalize_chunk_text(None)

        assert result == ""
