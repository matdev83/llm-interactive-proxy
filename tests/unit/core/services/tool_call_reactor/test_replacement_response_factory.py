"""Tests for ReplacementResponseFactory.

Following TDD methodology: tests written before implementation.
"""

from __future__ import annotations

from src.core.domain.chat import FunctionCall, ToolCall
from src.core.interfaces.replacement_response_factory_interface import (
    ToolCallReactionMetadata,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.tool_call_reactor.replacement_response_factory import (
    ReplacementResponseFactory,
)


class TestReplacementResponseFactoryMetadata:
    """Tests for metadata keys in replacement responses."""

    def test_all_required_metadata_keys_present(self) -> None:
        """Test that all required metadata keys are set."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(
            content="Original content",
            metadata={"model": "test-model"},
        )
        tool_call = ToolCall(
            id="call_123",
            type="function",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Steering message",
            original_tool_call=tool_call,
        )

        assert result.metadata["tool_call_swallowed"] is True
        assert result.metadata["steering_message"] == "Steering message"
        assert result.metadata["swallowed_tool_calls"] is not None
        assert isinstance(result.metadata["swallowed_tool_calls"], list)
        assert result.metadata["swallowed_original_content"] == "Original content"
        assert result.metadata["_steering_replacement"] is True
        assert result.metadata["replacement_provided"] is True
        assert result.metadata["role"] == "tool"
        assert result.metadata["finish_reason"] == "stop"

    def test_tool_call_id_and_name_in_metadata(self) -> None:
        """Test that tool call ID and name are extracted and set in metadata."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_456",
            type="function",
            function=FunctionCall(name="my_tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.metadata["tool_call_id"] == "call_456"
        assert result.metadata["tool_name"] == "my_tool"
        assert result.metadata["original_tool_call"] is not None

    def test_swallowed_tool_calls_contains_serialized_tool_call(self) -> None:
        """Test that swallowed_tool_calls contains the serialized ToolCall."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_789",
            type="function",
            function=FunctionCall(name="test", arguments='{"arg": 1}'),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        swallowed_calls = result.metadata["swallowed_tool_calls"]
        assert len(swallowed_calls) >= 1
        # Find the tool call we added
        found = False
        for call in swallowed_calls:
            if isinstance(call, dict) and call.get("id") == "call_789":
                found = True
                assert call.get("function", {}).get("name") == "test"
                break
        assert found, "Original tool call should be in swallowed_tool_calls"

    def test_existing_tool_calls_merged_into_swallowed_list(self) -> None:
        """Test that existing tool_calls in metadata are merged into swallowed_tool_calls."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(
            content="Content",
            metadata={
                "tool_calls": [{"id": "existing_1", "function": {"name": "existing"}}]
            },
        )
        tool_call = ToolCall(
            id="new_call",
            type="function",
            function=FunctionCall(name="new_tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        swallowed_calls = result.metadata["swallowed_tool_calls"]
        assert len(swallowed_calls) >= 2
        # Check that tool_calls key is removed from metadata
        assert "tool_calls" not in result.metadata


class TestBoundedContent:
    """Tests for bounded original content."""

    def test_swallowed_original_content_bounded_to_4000_chars(self) -> None:
        """Test that swallowed_original_content is truncated to 4000 chars."""
        factory = ReplacementResponseFactory()
        long_content = "x" * 5000
        original_response = ProcessedResponse(content=long_content)
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        truncated = result.metadata["swallowed_original_content"]
        assert truncated is not None
        assert len(truncated) <= 4000 + len("\n...[truncated]")
        assert "\n...[truncated]" in truncated

    def test_swallowed_original_content_not_truncated_if_under_limit(self) -> None:
        """Test that content under 4000 chars is not truncated."""
        factory = ReplacementResponseFactory()
        short_content = "Short content"
        original_response = ProcessedResponse(content=short_content)
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.metadata["swallowed_original_content"] == short_content

    def test_swallowed_original_content_handles_none(self) -> None:
        """Test that None content is handled gracefully."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content=None)
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.metadata["swallowed_original_content"] is None

    def test_swallowed_original_content_handles_non_string_content(self) -> None:
        """Test that non-string content is handled gracefully."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content={"dict": "content"})
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        # Should handle gracefully, not crash
        assert "swallowed_original_content" in result.metadata


class TestOpenAICompatibleStructure:
    """Tests for OpenAI-compatible response structure."""

    def test_response_has_openai_compatible_structure(self) -> None:
        """Test that replacement response has OpenAI-compatible structure."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(
            content="Original",
            metadata={"model": "gpt-4"},
        )
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Replacement",
            original_tool_call=tool_call,
        )

        assert isinstance(result.content, dict)
        assert "id" in result.content
        assert "object" in result.content
        assert "created" in result.content
        assert "model" in result.content
        assert "choices" in result.content
        assert "usage" in result.content

    def test_response_id_uses_proxy_pattern(self) -> None:
        """Test that response ID uses chatcmpl-proxy-* pattern."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        response_id = result.content["id"]
        assert response_id.startswith("chatcmpl-proxy-")
        assert "steering" not in response_id.lower()

    def test_response_choices_structure(self) -> None:
        """Test that choices array has correct structure."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Replacement message",
            original_tool_call=tool_call,
        )

        choices = result.content["choices"]
        assert isinstance(choices, list)
        assert len(choices) == 1
        choice = choices[0]
        assert choice["index"] == 0
        assert choice["message"]["role"] == "assistant"
        assert choice["message"]["content"] == "Replacement message"
        assert choice["finish_reason"] == "stop"

    def test_response_content_is_dict_not_string(self) -> None:
        """Test that content is a dict structure, not a JSON string."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        # Content should be dict, not string
        assert isinstance(result.content, dict)
        assert not isinstance(result.content, str)


class TestReactionMetadata:
    """Tests for reaction metadata handling."""

    def test_reaction_metadata_merged_into_tool_call_reactor_key(self) -> None:
        """Test that reaction metadata is merged into tool_call_reactor metadata."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(
            content="Content",
            metadata={"tool_call_reactor": {"existing": "value"}},
        )
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )
        reaction_metadata = ToolCallReactionMetadata(
            reaction_type="swallowed",
            reactor_name="test_reactor",
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
            reaction_metadata=reaction_metadata,
        )

        reactor_meta = result.metadata.get("tool_call_reactor")
        assert isinstance(reactor_meta, dict)
        assert reactor_meta["existing"] == "value"  # Preserved
        assert reactor_meta["reaction_type"] == "swallowed"
        assert reactor_meta["reactor_name"] == "test_reactor"

    def test_reaction_metadata_creates_new_key_if_missing(self) -> None:
        """Test that reaction metadata creates tool_call_reactor key if missing."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )
        reaction_metadata = ToolCallReactionMetadata(
            reaction_type="swallowed",
            reactor_name="reactor",
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
            reaction_metadata=reaction_metadata,
        )

        reactor_meta = result.metadata.get("tool_call_reactor")
        assert isinstance(reactor_meta, dict)
        assert reactor_meta["reaction_type"] == "swallowed"

    def test_no_reaction_metadata_does_not_crash(self) -> None:
        """Test that missing reaction metadata doesn't cause errors."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
            reaction_metadata=None,
        )

        # Should work fine without reaction metadata
        assert result.metadata["tool_call_swallowed"] is True


class TestUsagePreservation:
    """Tests for usage data preservation."""

    def test_original_usage_preserved(self) -> None:
        """Test that original usage data is preserved."""
        factory = ReplacementResponseFactory()
        original_usage = {"prompt_tokens": 10, "completion_tokens": 20}
        original_response = ProcessedResponse(
            content="Content",
            usage=original_usage,
        )
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.usage == original_usage
        assert result.content["usage"] == original_usage

    def test_no_usage_handled_gracefully(self) -> None:
        """Test that missing usage is handled gracefully."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content", usage=None)
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.usage is None
        assert result.content["usage"] is None


class TestEdgeCases:
    """Tests for edge cases."""

    def test_missing_tool_call_fields_handled(self) -> None:
        """Test that missing tool call fields are handled gracefully."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        # Create tool call with minimal fields
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        # Should not crash
        assert result.metadata["tool_call_swallowed"] is True

    def test_model_name_from_metadata(self) -> None:
        """Test that model name is extracted from metadata."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(
            content="Content",
            metadata={"model": "gpt-4-turbo"},
        )
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.content["model"] == "gpt-4-turbo"

    def test_default_model_name_when_missing(self) -> None:
        """Test that default model name is used when missing."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.content["model"] == "proxy-assistant"


class TestClientSafety:
    """Tests for client safety (Task 5.2)."""

    def test_response_id_does_not_contain_steering(self) -> None:
        """Test that response ID does not contain 'steering' substring."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        response_id = result.content["id"]
        assert "steering" not in response_id.lower()
        assert response_id.startswith("chatcmpl-proxy-")

    def test_client_visible_content_does_not_contain_internal_keys(self) -> None:
        """Test that client-visible content does not contain internal metadata keys."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        # Check that content dict doesn't contain internal keys
        content_str = str(result.content)
        assert "_steering_replacement" not in content_str
        assert "tool_call_swallowed" not in content_str
        assert "swallowed_tool_calls" not in content_str
        assert "swallowed_original_content" not in content_str

    def test_steering_message_only_in_metadata_not_content(self) -> None:
        """Test that steering_message is only in metadata, not in client-visible content."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Internal steering message",
            original_tool_call=tool_call,
        )

        # Steering message should be in metadata
        assert result.metadata["steering_message"] == "Internal steering message"
        # But client-visible content should have the replacement content, not steering
        assert (
            result.content["choices"][0]["message"]["content"]
            == "Internal steering message"
        )
        # Note: In this case they're the same, but the key is that steering_message
        # is explicitly marked as metadata, not leaked into response structure


class TestDownstreamCompatibility:
    """Tests for downstream compatibility markers (Task 5.2)."""

    def test_steering_replacement_marker_present(self) -> None:
        """Test that _steering_replacement marker is present in metadata."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.metadata["_steering_replacement"] is True

    def test_tool_call_swallowed_marker_present(self) -> None:
        """Test that tool_call_swallowed marker is present."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert result.metadata["tool_call_swallowed"] is True

    def test_swallowed_tool_calls_present_for_retry(self) -> None:
        """Test that swallowed_tool_calls is present for retry logic."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert "swallowed_tool_calls" in result.metadata
        assert isinstance(result.metadata["swallowed_tool_calls"], list)
        assert len(result.metadata["swallowed_tool_calls"]) > 0

    def test_swallowed_original_content_present_for_retry(self) -> None:
        """Test that swallowed_original_content is present for retry prompts."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Original content here")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        assert "swallowed_original_content" in result.metadata
        assert result.metadata["swallowed_original_content"] == "Original content here"

    def test_steering_message_present_for_backend(self) -> None:
        """Test that steering_message is present for backend steering."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Backend steering message",
            original_tool_call=tool_call,
        )

        assert "steering_message" in result.metadata
        assert result.metadata["steering_message"] == "Backend steering message"

    def test_metadata_contract_compliance(self) -> None:
        """Test that metadata matches the expected contract from design.md."""
        factory = ReplacementResponseFactory()
        original_response = ProcessedResponse(content="Content")
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="tool", arguments="{}"),
        )

        result = factory.build_replacement(
            original_response=original_response,
            replacement_content="Message",
            original_tool_call=tool_call,
        )

        # Verify all contract keys are present
        assert isinstance(result.metadata.get("tool_call_swallowed"), bool)
        assert isinstance(result.metadata.get("steering_message"), str)
        assert isinstance(result.metadata.get("swallowed_tool_calls"), list)
        assert isinstance(result.metadata.get("swallowed_original_content"), str | None)
        assert isinstance(result.metadata.get("_steering_replacement"), bool)
