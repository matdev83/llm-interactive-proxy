"""Tests for think tags fix middleware."""

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.think_tags_fix_middleware import (
    ThinkTagsFixFeature,
    ThinkTagsFixMiddleware,
)


class TestThinkTagsFixMiddleware:
    """Test cases for ThinkTagsFixMiddleware."""

    @pytest.mark.asyncio
    async def test_middleware_disabled(self):
        """Test that middleware does nothing when disabled."""
        middleware = ThinkTagsFixMiddleware(enabled=False)

        content = "<think>This is reasoning</think>This is the actual response"
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        # Should return original response unchanged
        assert result.content == content

    @pytest.mark.asyncio
    async def test_no_think_tags(self):
        """Test that content without think tags is unchanged."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "This is a normal response without any think tags"
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        # Should return original response unchanged
        assert result.content == content

    @pytest.mark.asyncio
    async def test_proper_think_tags_at_start(self):
        """Test fixing think tags that appear at the start of content."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = (
            "<think>This is my reasoning process</think>This is the actual response"
        )
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        # Should extract only the non-reasoning content
        assert result.content == "This is the actual response"
        assert result.metadata["think_tags_fixed"] is True
        assert result.metadata["reasoning"] == "This is my reasoning process"
        assert result.metadata["reasoning_format"] == "extracted_from_think_tags"
        assert result.metadata["reasoning_length"] == len(
            "This is my reasoning process"
        )

    @pytest.mark.asyncio
    async def test_think_tags_with_whitespace(self):
        """Test fixing think tags with surrounding whitespace."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "  <think>  Reasoning with spaces  </think>  Response content  "
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        # Should extract the non-reasoning content while preserving original whitespace
        assert result.content == "    Response content  "
        assert result.metadata["think_tags_fixed"] is True
        assert result.metadata["reasoning"] == "Reasoning with spaces"
        assert result.metadata["reasoning_format"] == "extracted_from_think_tags"

    @pytest.mark.asyncio
    async def test_preserve_leading_newline_and_indentation(self):
        """Ensure indentation-sensitive content remains intact after think tag removal."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "<think>reasoning</think>\n    return x"
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        assert result.content == "\n    return x"
        assert result.metadata["think_tags_fixed"] is True
        assert result.metadata["reasoning"] == "reasoning"

    @pytest.mark.asyncio
    async def test_incomplete_think_tags(self):
        """Test handling incomplete think tags (opening without closing)."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "<think>This is reasoning without proper closing"
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        # Should treat as pure reasoning and return empty content
        assert result.content == ""
        assert result.metadata["think_tags_fixed"] is True

    @pytest.mark.asyncio
    async def test_incomplete_think_tags_with_closing(self):
        """Test handling incomplete think tags that have closing tag."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "<think>This is reasoning</think>"
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        # Should treat as pure reasoning and return empty content
        assert result.content == ""
        assert result.metadata["think_tags_fixed"] is True

    @pytest.mark.asyncio
    async def test_case_insensitive_think_tags(self):
        """Test that think tags are handled case-insensitively."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "<THINK>Uppercase reasoning</THINK>Response content"
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        assert result.content == "Response content"
        assert result.metadata["think_tags_fixed"] is True

    @pytest.mark.asyncio
    async def test_multiline_think_tags(self):
        """Test handling multiline think tags."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = """<think>
This is multiline reasoning
with multiple lines
of thought process
</think>This is the actual response"""
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        assert result.content == "This is the actual response"
        assert result.metadata["think_tags_fixed"] is True

    @pytest.mark.asyncio
    async def test_think_tags_not_at_start(self):
        """Test that think tags not at the start are ignored."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "Some content first <think>reasoning</think> more content"
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        # Should return original content unchanged since think tags are not at start
        assert result.content == content
        # No metadata should be added since no fix was applied
        assert result.metadata is None or not result.metadata.get(
            "think_tags_fixed", False
        )

    @pytest.mark.asyncio
    async def test_empty_content(self):
        """Test handling empty or None content."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Test empty string
        response = ProcessedResponse(content="")
        result = await middleware.process(response, "session1", {})
        assert result.content == ""

        # Test None content
        response = ProcessedResponse(content=None)
        result = await middleware.process(response, "session1", {})
        assert result.content is None

    @pytest.mark.asyncio
    async def test_preserve_metadata_and_usage(self):
        """Test that existing metadata and usage are preserved."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        original_metadata = {"existing": "data"}
        original_usage = {"tokens": 100}

        content = "<think>reasoning</think>response"
        response = ProcessedResponse(
            content=content, metadata=original_metadata, usage=original_usage
        )

        result = await middleware.process(response, "session1", {})

        assert result.content == "response"
        assert result.usage == original_usage
        assert result.metadata["existing"] == "data"
        assert result.metadata["think_tags_fixed"] is True
        assert result.metadata["reasoning"] == "reasoning"
        assert result.metadata["reasoning_format"] == "extracted_from_think_tags"

    @pytest.mark.asyncio
    async def test_dict_response_format(self):
        """Test handling dict-format responses (like OpenAI format)."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        response_dict = {
            "choices": [
                {"message": {"content": "<think>reasoning</think>actual response"}}
            ],
            "usage": {"total_tokens": 50},
        }

        result = await middleware.process(response_dict, "session1", {})

        # For dict responses, the middleware returns the modified dict
        assert result["choices"][0]["message"]["content"] == "actual response"
        assert result["choices"][0]["message"]["reasoning"] == "reasoning"

    @pytest.mark.asyncio
    async def test_string_response_format(self):
        """Test handling plain string responses."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        response_str = "<think>reasoning</think>actual response"

        result = await middleware.process(response_str, "session1", {})

        assert result.content == "actual response"
        assert result.metadata["think_tags_fixed"] is True

    @pytest.mark.asyncio
    async def test_async_process(self):
        """Test that the async process method works correctly."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "<think>async reasoning</think>async response"
        response = ProcessedResponse(content=content)

        result = await middleware.process(response, "session1", {})

        assert result.content == "async response"
        assert result.metadata["think_tags_fixed"] is True

    def test_reset_session(self):
        """Test that reset_session doesn't raise errors (stateless middleware)."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Should not raise any errors
        middleware.reset_session("session1")


class TestThinkTagsFixFeatureParity:
    """Parity checks for ThinkTagsFixFeature vs legacy middleware behavior."""

    def test_backend_only_per_model_config_enabled(self) -> None:
        feature = ThinkTagsFixFeature(
            enabled=False,
            per_model_config={"openai": {"enabled": True}},
        )
        assert feature._should_process_for_model("openai", "gpt-4") is True
        assert feature._should_process_for_model("anthropic", "gpt-4") is False

    def test_backend_only_streaming_buffer_size(self) -> None:
        feature = ThinkTagsFixFeature(
            streaming_buffer_size=100,
            per_model_config={"openai": {"streaming_buffer_size": 999}},
        )
        assert feature._get_buffer_size_for_model("openai", "gpt-4") == 999
        assert feature._get_buffer_size_for_model("anthropic", "gpt-4") == 100

    @pytest.mark.asyncio
    async def test_streaming_uses_canonical_backend_and_model_context_keys(
        self,
    ) -> None:
        feature = ThinkTagsFixFeature(
            enabled=False,
            per_model_config={"openai:gpt-4o-mini": {"enabled": True}},
        )
        first = await feature.process_chunk(
            ProcessedResponse(content="<think>r</think>"),
            "s1",
            {"backend_name": "openai", "model_name": "gpt-4o-mini"},
            is_streaming=True,
        )
        assert isinstance(first, ProcessedResponse)
        assert first.content == ""

        result = await feature.process_chunk(
            ProcessedResponse(content="Hello"),
            "s1",
            {"backend_name": "openai", "model_name": "gpt-4o-mini"},
            is_streaming=True,
        )
        assert isinstance(result, ProcessedResponse)
        assert result.content == "Hello"
        assert result.metadata is not None
        assert result.metadata["reasoning"] == "r"
        assert result.metadata["streaming_extraction"] is True

    @pytest.mark.asyncio
    async def test_non_streaming_pure_reasoning_open_tag_only(self) -> None:
        feature = ThinkTagsFixFeature(enabled=True)
        response = ProcessedResponse(
            content="<think>This is just reasoning without any actual response"
        )
        result = await feature.process_chunk(
            response,
            "session1",
            {"backend": "b", "model": "m"},
            is_streaming=False,
        )
        assert isinstance(result, ProcessedResponse)
        assert result.content == ""
        assert result.metadata["reasoning"] == (
            "This is just reasoning without any actual response"
        )
        assert result.metadata["think_tags_fixed"] is True
        assert result.metadata["reasoning_format"] == "extracted_from_think_tags"

    @pytest.mark.asyncio
    async def test_non_streaming_full_tags_matches_middleware(self) -> None:
        feature = ThinkTagsFixFeature(enabled=True)
        content = "<think>r</think>Hello"
        response = ProcessedResponse(content=content)
        result = await feature.process_chunk(
            response, "s1", {"backend": "b", "model": "m"}, is_streaming=False
        )
        assert result.content == "Hello"
        assert result.metadata["reasoning"] == "r"
        assert result.metadata["think_tags_fixed"] is True
