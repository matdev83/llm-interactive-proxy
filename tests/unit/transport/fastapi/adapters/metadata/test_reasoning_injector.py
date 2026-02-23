"""Tests for ReasoningInjector."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
    ReasoningInjector,
)


class TestReasoningInjector:
    """Test ReasoningInjector implementation."""

    def test_inject_reasoning_into_delta_streaming(self) -> None:
        """Test reasoning injection into delta for streaming responses."""
        injector = ReasoningInjector()
        content = {
            "choices": [
                {
                    "delta": {
                        "content": "Hello",
                        "role": "assistant",
                    }
                }
            ]
        }
        metadata = {
            "reasoning_content": "Let me think about this...",
            "reasoning": "Let me think about this...",
        }

        result = injector.inject_reasoning(content, metadata, streaming=True)

        assert isinstance(result, dict)
        assert (
            result["choices"][0]["delta"]["reasoning_content"]
            == "Let me think about this..."
        )
        assert (
            result["choices"][0]["delta"]["reasoning"] == "Let me think about this..."
        )
        assert result["choices"][0]["delta"]["content"] == "Hello"

    def test_suppress_reasoning_fields_skips_injection(self) -> None:
        injector = ReasoningInjector()
        content = {
            "choices": [
                {
                    "delta": {
                        "content": "Hello",
                        "role": "assistant",
                    }
                }
            ]
        }
        metadata = {
            "reasoning_content": "Hidden",
            "_suppress_reasoning_fields": True,
        }

        result = injector.inject_reasoning(content, metadata, streaming=True)

        assert isinstance(result, dict)
        assert "reasoning_content" not in result["choices"][0]["delta"]
        assert "reasoning" not in result["choices"][0]["delta"]

    def test_inject_reasoning_into_message_non_streaming(self) -> None:
        """Test reasoning injection into message for non-streaming responses."""
        injector = ReasoningInjector()
        content = {
            "choices": [
                {
                    "message": {
                        "content": "Hello",
                        "role": "assistant",
                    }
                }
            ]
        }
        metadata = {
            "reasoning_content": "Let me think about this...",
        }

        result = injector.inject_reasoning(content, metadata, streaming=False)

        assert isinstance(result, dict)
        assert (
            result["choices"][0]["message"]["reasoning_content"]
            == "Let me think about this..."
        )
        assert (
            result["choices"][0]["message"]["reasoning"] == "Let me think about this..."
        )

    def test_no_overwrite_existing_reasoning_values(self) -> None:
        """Test that existing reasoning values are not overwritten."""
        injector = ReasoningInjector()
        content = {
            "choices": [
                {
                    "delta": {
                        "content": "Hello",
                        "reasoning_content": "Existing reasoning",
                        "reasoning": "Existing reasoning",
                    }
                }
            ]
        }
        metadata = {
            "reasoning_content": "New reasoning",
        }

        result = injector.inject_reasoning(content, metadata, streaming=True)

        assert (
            result["choices"][0]["delta"]["reasoning_content"] == "Existing reasoning"
        )
        assert result["choices"][0]["delta"]["reasoning"] == "Existing reasoning"

        # Strict OpenAI clients may reject non-standard top-level `metadata` fields.
        # When reasoning already exists in delta, the injector should not add
        # a top-level `metadata` fallback.
        assert "metadata" not in result

    def test_build_streaming_payload_for_non_dict_content(self) -> None:
        """Test OpenAI envelope building for non-dict content."""
        injector = ReasoningInjector()
        content = "Simple text content"
        metadata = {
            "id": "test-id",
            "model": "test-model",
            "reasoning_content": "Let me think...",
        }

        result = injector.build_streaming_payload(content, metadata, streaming=True)

        assert isinstance(result, dict)
        assert result["id"] == "test-id"
        assert result["model"] == "test-model"
        assert result["object"] == "chat.completion.chunk"
        assert "choices" in result
        assert result["choices"][0]["delta"]["content"] == "Simple text content"
        assert result["choices"][0]["delta"]["reasoning_content"] == "Let me think..."

    def test_build_streaming_payload_includes_tool_calls(self) -> None:
        """Test that tool_calls from metadata are included in payload."""
        injector = ReasoningInjector()
        content = "Some content"
        metadata = {
            "id": "test-id",
            "model": "test-model",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "test_func"}}
            ],
        }

        result = injector.build_streaming_payload(content, metadata, streaming=True)

        assert "tool_calls" in result["choices"][0]["delta"]
        assert result["choices"][0]["delta"]["tool_calls"] == metadata["tool_calls"]

    def test_build_streaming_payload_generates_id_when_missing(self) -> None:
        """Test that ID is generated when missing from metadata."""
        injector = ReasoningInjector()
        content = "Content"
        metadata = {"model": "test-model"}

        result = injector.build_streaming_payload(content, metadata, streaming=True)

        assert "id" in result
        assert result["id"].startswith("chatcmpl-")
        assert len(result["id"]) > len("chatcmpl-")

    def test_build_streaming_payload_non_streaming_mode(self) -> None:
        """Test payload building for non-streaming mode."""
        injector = ReasoningInjector()
        content = "Content"
        metadata = {"model": "test-model"}

        result = injector.build_streaming_payload(content, metadata, streaming=False)

        assert result["object"] == "chat.completion"
        assert "message" in result["choices"][0]
        assert "delta" not in result["choices"][0]

    def test_inject_reasoning_no_metadata(self) -> None:
        """Test that content is returned unchanged when no metadata."""
        injector = ReasoningInjector()
        content = {"choices": [{"delta": {"content": "Hello"}}]}

        result = injector.inject_reasoning(content, {}, streaming=True)

        assert result == content

    def test_inject_reasoning_surfaces_via_metadata_when_no_choices(self) -> None:
        """Test that reasoning is surfaced via metadata block when no choices."""
        injector = ReasoningInjector()
        content = {"some": "data"}
        metadata = {"reasoning_content": "Let me think..."}

        result = injector.inject_reasoning(content, metadata, streaming=False)

        assert "metadata" in result
        assert result["metadata"]["reasoning_content"] == "Let me think..."

    def test_inject_reasoning_string_content_with_reasoning(self) -> None:
        """Test injection with string content that has reasoning."""
        injector = ReasoningInjector()
        content = "Simple text"
        metadata = {"reasoning_content": "Let me think..."}

        result = injector.inject_reasoning(content, metadata, streaming=True)

        assert isinstance(result, dict)
        assert result["choices"][0]["delta"]["content"] == "Simple text"
        assert result["choices"][0]["delta"]["reasoning_content"] == "Let me think..."

    def test_inject_reasoning_tool_calls_in_metadata_non_streaming(self) -> None:
        """Test that tool_calls in metadata trigger payload building for non-streaming."""
        injector = ReasoningInjector()
        content = "Simple text"
        metadata = {
            "tool_calls": [{"id": "call_1", "type": "function"}],
        }

        result = injector.inject_reasoning(content, metadata, streaming=False)

        assert isinstance(result, dict)
        assert "choices" in result
        assert result["choices"][0]["message"]["tool_calls"] == metadata["tool_calls"]

    def test_normalize_content_preserves_stop_chunk(self) -> None:
        """Test that StopChunkWithUsage is preserved during normalization."""
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        injector = ReasoningInjector()
        stop_chunk = StopChunkWithUsage({"usage": {"total_tokens": 100}})
        metadata: dict[str, object] = {}

        result = injector.inject_reasoning(stop_chunk, metadata, streaming=True)

        assert isinstance(result, StopChunkWithUsage)
        assert result == stop_chunk

    def test_normalize_content_handles_dataclass(self) -> None:
        """Test that dataclasses are normalized to dicts."""

        @dataclass
        class TestData:
            content: str

        injector = ReasoningInjector()
        test_data = TestData("test")
        metadata = {"reasoning_content": "thinking"}

        result = injector.inject_reasoning(test_data, metadata, streaming=True)

        assert isinstance(result, dict)
        assert result["content"] == "test"
