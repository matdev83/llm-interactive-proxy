"""
Tests for ChatController message content normalization functionality.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.app.controllers.chat_controller import ChatController
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.usage_summary import UsageSummary


class TestCoerceMessageContentToText:
    """Test cases for _coerce_message_content_to_text method."""

    def test_coerce_message_content_to_text_handles_string(self) -> None:
        """String content should be returned as-is."""
        content = "Hello, world!"
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "Hello, world!"

    def test_coerce_message_content_to_text_handles_bytes(self) -> None:
        """Bytes content should be decoded as UTF-8."""
        content = b"Hello, world!"
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "Hello, world!"

    def test_coerce_message_content_to_text_handles_none(self) -> None:
        """None input should return empty string."""
        result = ChatController._coerce_message_content_to_text(None)
        assert result == ""

    def test_coerce_message_content_to_text_handles_empty_sequence(self) -> None:
        """Empty sequences should return empty string."""
        result = ChatController._coerce_message_content_to_text([])
        assert result == ""

    def test_coerce_message_content_to_text_handles_dict_with_text(self) -> None:
        """Dict with text field should extract text value."""
        content = {"text": "Hello from dict"}
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "Hello from dict"

    def test_coerce_message_content_to_text_handles_dict_with_bytes_text(self) -> None:
        """Dict with bytes text field should decode bytes."""
        content = {"text": b"Hello from bytes"}
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "Hello from bytes"

    def test_coerce_message_content_to_text_extracts_image_url(self) -> None:
        """Image URL content should extract the URL string."""
        content = {
            "type": "image_url",
            "image_url": {"url": "https://example.com/image.png"},
        }
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "https://example.com/image.png"

    def test_coerce_message_content_to_text_handles_dict_without_text(self) -> None:
        """Dict without text should JSON serialize."""
        content = {"key": "value", "number": 42}
        result = ChatController._coerce_message_content_to_text(content)
        assert result == json.dumps(content, ensure_ascii=False)

    def test_coerce_message_content_to_text_handles_sequence(self) -> None:
        """Sequence should flatten parts with double newlines."""
        content = ["Part 1", "Part 2", "Part 3"]
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "Part 1\n\nPart 2\n\nPart 3"

    def test_coerce_message_content_to_text_handles_nested_sequence(self) -> None:
        """Nested sequences should be flattened recursively."""
        content = ["Outer 1", ["Inner 1", "Inner 2"], "Outer 2"]
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "Outer 1\n\nInner 1\n\nInner 2\n\nOuter 2"

    def test_coerce_message_content_to_text_handles_mixed_sequence(self) -> None:
        """Mixed sequence should handle different types."""
        content = ["Text part", {"text": "Dict part"}, b"Bytes part"]
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "Text part\n\nDict part\n\nBytes part"

    def test_coerce_message_content_to_text_handles_object_with_model_dump(
        self,
    ) -> None:
        """Objects with model_dump should use dumped content."""

        class TestModel:
            def model_dump(self) -> dict[str, Any]:
                return {"text": "From model_dump"}

        content = TestModel()
        result = ChatController._coerce_message_content_to_text(content)
        assert result == "From model_dump"

    def test_coerce_message_content_to_text_handles_object_with_text_attr(self) -> None:
        """Objects with text attribute should return the text value."""

        class CustomObject:
            text = "custom content"

        result = ChatController._coerce_message_content_to_text(CustomObject())
        assert result == "custom content"

    def test_coerce_message_content_to_text_handles_object_with_bytes_text_attr(
        self,
    ) -> None:
        """Objects with bytes text attribute should decode bytes."""

        class CustomObject:
            text = b"custom content"

        result = ChatController._coerce_message_content_to_text(CustomObject())
        assert result == "custom content"

    def test_coerce_message_content_to_text_fallback_to_str(self) -> None:
        """Unknown objects should fallback to str()."""

        class CustomObject:
            def __str__(self) -> str:
                return "string representation"

        result = ChatController._coerce_message_content_to_text(CustomObject())
        assert result == "string representation"

    def test_coerce_message_content_to_text_handles_model_dump_exception(self) -> None:
        """Objects with failing model_dump should continue processing."""

        class TestModel:
            def model_dump(self) -> dict[str, Any]:
                raise RuntimeError("Dump failed")

        content = TestModel()
        result = ChatController._coerce_message_content_to_text(content)
        assert result == str(content)

    def test_coerce_message_content_to_text_prevents_stack_overflow(self) -> None:
        """Circular references should not cause stack overflow."""
        # Create a circular reference
        content: dict[str, Any] = {}
        content["self"] = content

        # This should not raise RecursionError but should handle circular reference gracefully
        result = ChatController._coerce_message_content_to_text(content)
        # Should return some string representation without infinite recursion
        assert isinstance(result, str)
        assert len(result) > 0
        # The result should contain some indication of the circular reference
        assert "Circular reference detected" in result


class TestEnsureOpenAIChatSchemaUsage:
    @pytest.mark.asyncio
    async def test_tool_calls_schema_preserves_metadata_usage(self) -> None:
        processor = AsyncMock()
        processor.process_request = AsyncMock(
            return_value=ResponseEnvelope(
                content='[{"type": "function", "id": "call_1", "function": {"name": "do_work", "arguments": "{}"}}]',
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "do_work", "arguments": "{}"},
                        }
                    ],
                    "usage": {
                        "input_tokens": 19,
                        "output_tokens": 7,
                        "total_tokens": 26,
                    },
                },
            )
        )

        controller = ChatController(
            request_processor=processor,
            translation_service=None,
            wire_capture=None,
            metrics_initializer=None,
        )

        request = Mock()
        request.body = AsyncMock(return_value=b"{}")
        request.headers = {}
        request.cookies = {}
        request.url = Mock()
        request.url.path = "/v1/chat/completions"
        request.state = Mock()
        request.app = Mock()
        request.app.state = Mock()
        request.app.state.service_provider = None

        from src.core.domain.chat import ChatMessage, ChatRequest

        request_data = ChatRequest(
            model="openai-codex:gpt-5-codex",
            messages=[ChatMessage(role="user", content="hello")],
            stream=False,
        )

        response = await controller.handle_chat_completion(request, request_data)
        body = (
            response.body.tobytes()
            if isinstance(response.body, memoryview)
            else response.body
        )
        payload = json.loads(body.decode("utf-8"))

        usage = UsageSummary.from_dict(payload["usage"])
        assert usage.prompt_tokens == 19
        assert usage.completion_tokens == 7
        assert usage.total_tokens == 26
