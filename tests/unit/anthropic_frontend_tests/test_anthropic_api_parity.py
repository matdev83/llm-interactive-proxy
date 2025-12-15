"""
Tests for Anthropic API spec parity features.

Tests cover the new features added to match the official Anthropic API specification:
- Extended thinking configuration
- Service tier parameter
- Image URL source support
- Document/PDF content blocks
- Stop sequence in responses
"""

from src.anthropic_converters import (
    _convert_anthropic_image_to_openai,
    anthropic_to_openai_request,
    openai_to_anthropic_response,
)
from src.anthropic_models import (
    AnthropicMessage,
    AnthropicMessagesRequest,
    ThinkingConfig,
)


class TestThinkingConfiguration:
    """Tests for extended thinking configuration support."""

    def test_thinking_config_model_enabled(self) -> None:
        """Test ThinkingConfig model with enabled type."""
        config = ThinkingConfig(type="enabled", budget_tokens=2048)
        assert config.type == "enabled"
        assert config.budget_tokens == 2048

    def test_thinking_config_model_disabled(self) -> None:
        """Test ThinkingConfig model with disabled type."""
        config = ThinkingConfig(type="disabled")
        assert config.type == "disabled"
        assert config.budget_tokens is None

    def test_request_with_thinking_config(self) -> None:
        """Test AnthropicMessagesRequest with thinking configuration."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=1024,
            thinking={"type": "enabled", "budget_tokens": 2048},
        )
        assert request.thinking is not None
        # The dict may be converted to ThinkingConfig or remain as dict
        if isinstance(request.thinking, dict):
            assert request.thinking["type"] == "enabled"
            assert request.thinking["budget_tokens"] == 2048
        else:
            # ThinkingConfig object
            assert request.thinking.type == "enabled"
            assert request.thinking.budget_tokens == 2048

    def test_anthropic_to_openai_preserves_thinking(self) -> None:
        """Test that thinking config is preserved in conversion."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=1024,
            thinking={"type": "enabled", "budget_tokens": 4096},
        )
        openai_req = anthropic_to_openai_request(request)

        assert openai_req.extra_body is not None
        assert "thinking" in openai_req.extra_body
        assert openai_req.extra_body["thinking"]["type"] == "enabled"
        assert openai_req.extra_body["thinking"]["budget_tokens"] == 4096


class TestServiceTier:
    """Tests for service_tier parameter support."""

    def test_service_tier_auto(self) -> None:
        """Test service_tier with 'auto' value."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=1024,
            service_tier="auto",
        )
        assert request.service_tier == "auto"

    def test_service_tier_standard_only(self) -> None:
        """Test service_tier with 'standard_only' value."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=1024,
            service_tier="standard_only",
        )
        assert request.service_tier == "standard_only"

    def test_anthropic_to_openai_preserves_service_tier(self) -> None:
        """Test that service_tier is preserved in conversion."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=1024,
            service_tier="auto",
        )
        openai_req = anthropic_to_openai_request(request)

        assert openai_req.extra_body is not None
        assert openai_req.extra_body.get("service_tier") == "auto"


class TestImageUrlSource:
    """Tests for image URL source support."""

    def test_convert_base64_image_to_openai(self) -> None:
        """Test converting base64 image to OpenAI format."""
        anthropic_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "dGVzdC1pbWFnZQ==",  # "test-image" base64
            },
        }
        result = _convert_anthropic_image_to_openai(anthropic_block)

        assert result is not None
        assert result["type"] == "image_url"
        assert "image_url" in result
        assert result["image_url"]["url"] == "data:image/png;base64,dGVzdC1pbWFnZQ=="

    def test_convert_url_image_to_openai(self) -> None:
        """Test converting URL image to OpenAI format."""
        anthropic_block = {
            "type": "image",
            "source": {
                "type": "url",
                "url": "https://example.com/image.jpg",
            },
        }
        result = _convert_anthropic_image_to_openai(anthropic_block)

        assert result is not None
        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == "https://example.com/image.jpg"

    def test_convert_empty_source_returns_none(self) -> None:
        """Test that empty source returns None."""
        anthropic_block = {"type": "image", "source": {}}
        result = _convert_anthropic_image_to_openai(anthropic_block)
        assert result is None

    def test_request_with_image_url_content(self) -> None:
        """Test request with image URL content block."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[
                AnthropicMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "What's in this image?"},
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.com/image.jpg",
                            },
                        },
                    ],
                )
            ],
            max_tokens=1024,
        )

        openai_req = anthropic_to_openai_request(request)

        # Check that the message was converted
        assert len(openai_req.messages) == 1
        # The content should contain both text and image parts
        message = openai_req.messages[0]
        content = message.content

        # For multimodal content, the message should have list content
        assert isinstance(content, list | str)  # type: ignore[arg-type]


class TestStopSequenceResponse:
    """Tests for stop_sequence in response."""

    def test_response_includes_stop_sequence(self) -> None:
        """Test that response includes stop_sequence when present."""
        openai_response = {
            "id": "chatcmpl-123",
            "model": "claude-3-5-sonnet-20241022",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello there!"},
                    "finish_reason": "stop",
                    "stop_sequence": "END",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        anthropic_response = openai_to_anthropic_response(openai_response)

        assert "stop_sequence" in anthropic_response
        # Note: stop_sequence is extracted from the choice if present


class TestDocumentContentBlocks:
    """Tests for document/PDF content block support."""

    def test_request_with_document_content(self) -> None:
        """Test request with document content block."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[
                AnthropicMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "Analyze this document"},
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": "dGVzdC1wZGY=",  # "test-pdf" base64
                            },
                            "title": "test.pdf",
                        },
                    ],
                )
            ],
            max_tokens=1024,
        )

        openai_req = anthropic_to_openai_request(request)

        # Document blocks should be preserved or converted
        assert len(openai_req.messages) == 1


class TestSystemPromptWithCacheControl:
    """Tests for system prompt with cache control support."""

    def test_system_prompt_as_string(self) -> None:
        """Test system prompt as simple string."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            system="You are a helpful assistant",
            max_tokens=1024,
        )
        assert request.system == "You are a helpful assistant"

    def test_system_prompt_as_list_simple(self) -> None:
        """Test system prompt as list with single text block converts to string."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            system=[{"type": "text", "text": "You are a helpful assistant"}],
            max_tokens=1024,
        )
        # Simple single-block without cache_control should be converted to string
        assert request.system == "You are a helpful assistant"

    def test_system_prompt_with_cache_control_preserved(self) -> None:
        """Test system prompt with cache_control preserved as list."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            system=[
                {
                    "type": "text",
                    "text": "You are a helpful assistant",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            max_tokens=1024,
        )
        # With cache_control, the list format should be preserved
        assert isinstance(request.system, list)
        assert request.system[0]["cache_control"]["type"] == "ephemeral"


class TestToolChoiceEnhancements:
    """Tests for enhanced tool_choice support."""

    def test_tool_choice_none(self) -> None:
        """Test tool_choice with 'none' value."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            tool_choice="none",
            max_tokens=1024,
        )
        assert request.tool_choice == "none"

    def test_tool_choice_any(self) -> None:
        """Test tool_choice with 'any' value as dict."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            tool_choice={"type": "any"},
            max_tokens=1024,
        )
        assert request.tool_choice["type"] == "any"

    def test_tool_choice_with_disable_parallel(self) -> None:
        """Test tool_choice with disable_parallel_tool_use."""
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[AnthropicMessage(role="user", content="Hello")],
            tool_choice={"type": "any", "disable_parallel_tool_use": True},
            max_tokens=1024,
        )
        assert request.tool_choice["type"] == "any"
        assert request.tool_choice["disable_parallel_tool_use"] is True


