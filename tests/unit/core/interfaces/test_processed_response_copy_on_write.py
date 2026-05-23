"""
Unit tests for ProcessedResponse copy-on-write contract behavior.

These tests verify that ProcessedResponse instances preserve copy-on-write
semantics when updated during processing, ensuring that original instances
remain unchanged and new instances are created for modifications.

NFR1.3: When typed contracts are updated during processing, the LLM Proxy
shall preserve copy-on-write behavior rather than mutating canonical contracts in place.
"""

from __future__ import annotations

from pydantic.types import JsonValue
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestProcessedResponseCopyOnWrite:
    """Test copy-on-write behavior for ProcessedResponse contracts."""

    def test_processed_response_instances_are_immutable_by_default(self):
        """
        Verify that ProcessedResponse instances don't mutate when accessed.

        Accessing attributes should not modify the instance.
        """
        chunk = ProcessedResponse(
            content="test content",
            metadata={"key": "value"},
            usage=UsageSummary(prompt_tokens=10, completion_tokens=20),
        )

        # Store original values
        original_content = chunk.content
        original_metadata = dict(chunk.metadata)
        original_usage = chunk.usage

        # Access attributes multiple times
        _ = chunk.content
        _ = chunk.metadata
        _ = chunk.usage

        # Verify nothing changed
        assert chunk.content == original_content
        assert chunk.metadata == original_metadata
        assert chunk.usage == original_usage

    def test_metadata_updates_create_new_instances(self):
        """
        Verify that metadata updates create new ProcessedResponse instances.

        NFR1.3: Contract updates must preserve copy-on-write behavior.
        """
        original_metadata: dict[str, JsonValue] = {"key1": "value1", "key2": "value2"}
        original_chunk = ProcessedResponse(
            content="test", metadata=original_metadata  # type: ignore[arg-type]
        )

        # Create updated metadata
        updated_metadata: dict[str, JsonValue] = dict(original_metadata)
        updated_metadata["key3"] = "value3"

        # Create new chunk with updated metadata
        updated_chunk = ProcessedResponse(
            content=original_chunk.content,
            metadata=updated_metadata,  # type: ignore[arg-type]
            usage=original_chunk.usage,
        )

        # Verify original chunk is unchanged
        assert original_chunk.metadata == original_metadata
        assert "key3" not in original_chunk.metadata
        assert id(original_chunk) != id(updated_chunk)

        # Verify new chunk has updates
        assert updated_chunk.metadata["key3"] == "value3"
        assert updated_chunk.metadata["key1"] == "value1"

    def test_content_updates_create_new_instances(self):
        """
        Verify that content updates create new ProcessedResponse instances.
        """

        original_content: dict[str, JsonValue] = {
            "choices": [{"delta": {"content": "original"}}]
        }
        original_chunk = ProcessedResponse(
            content=original_content, metadata={"test": "value"}  # type: ignore[arg-type]
        )

        # Create updated content
        updated_content: dict[str, JsonValue] = {
            "choices": [{"delta": {"content": "updated"}}]
        }
        updated_chunk = ProcessedResponse(
            content=updated_content,  # type: ignore[arg-type]
            metadata=original_chunk.metadata,
            usage=original_chunk.usage,
        )

        # Verify original chunk is unchanged
        assert original_chunk.content == original_content
        # Type-safe access to nested dict structure
        if (
            isinstance(original_chunk.content, dict)
            and "choices" in original_chunk.content
        ):
            choices = original_chunk.content["choices"]
            if isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict) and "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict) and "content" in delta:
                        assert delta["content"] == "original"
        assert id(original_chunk) != id(updated_chunk)

        # Verify new chunk has updates
        assert updated_chunk.content == updated_content
        if (
            isinstance(updated_chunk.content, dict)
            and "choices" in updated_chunk.content
        ):
            choices = updated_chunk.content["choices"]
            if isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict) and "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict) and "content" in delta:
                        assert delta["content"] == "updated"

    def test_usage_updates_create_new_instances(self):
        """
        Verify that usage updates create new ProcessedResponse instances.
        """
        original_usage = UsageSummary(prompt_tokens=10, completion_tokens=20)
        original_chunk = ProcessedResponse(
            content="test", metadata={"test": "value"}, usage=original_usage
        )

        # Create updated usage
        updated_usage = UsageSummary(prompt_tokens=15, completion_tokens=25)
        updated_chunk = ProcessedResponse(
            content=original_chunk.content,
            metadata=original_chunk.metadata,
            usage=updated_usage,
        )

        # Verify original chunk is unchanged
        assert original_chunk.usage == original_usage
        assert original_chunk.usage.prompt_tokens == 10
        assert id(original_chunk) != id(updated_chunk)

        # Verify new chunk has updates
        assert updated_chunk.usage == updated_usage
        assert updated_chunk.usage.prompt_tokens == 15

    def test_dict_content_not_mutated_when_metadata_merged(self):
        """
        Verify that dict content is not mutated in-place when metadata is merged.

        When creating a new ProcessedResponse with merged metadata, the original
        dict content should remain unchanged and be shared (not copied).
        """
        original_dict = {"key": "value", "nested": {"inner": "data"}}
        original_chunk = ProcessedResponse(
            content=original_dict, metadata={"meta": "data"}
        )

        # Store original dict identity
        original_dict_id = id(original_chunk.content)

        # Merge metadata
        merged_metadata = dict(original_chunk.metadata)
        merged_metadata["new_meta"] = "new_data"

        # Create new chunk with merged metadata
        updated_chunk = ProcessedResponse(
            content=original_chunk.content,
            metadata=merged_metadata,
            usage=original_chunk.usage,
        )

        # Verify original dict content is unchanged
        assert original_chunk.content == original_dict
        assert id(original_chunk.content) == original_dict_id

        # Verify dict content is shared (not copied) - same object identity
        assert id(updated_chunk.content) == original_dict_id

        # Verify metadata was updated
        assert updated_chunk.metadata["new_meta"] == "new_data"
        assert original_chunk.metadata["meta"] == "data"  # Original unchanged

    def test_string_content_not_mutated_when_metadata_merged(self):
        """
        Verify that string content is not mutated in-place when metadata is merged.
        """
        original_string = "test content"
        original_chunk = ProcessedResponse(
            content=original_string, metadata={"meta": "data"}
        )

        # Store original string identity
        id(original_chunk.content)

        # Merge metadata
        merged_metadata = dict(original_chunk.metadata)
        merged_metadata["new_meta"] = "new_data"

        # Create new chunk with merged metadata
        updated_chunk = ProcessedResponse(
            content=original_chunk.content,
            metadata=merged_metadata,
            usage=original_chunk.usage,
        )

        # Verify original string content is unchanged
        assert original_chunk.content == original_string
        # Strings are immutable in Python, so identity check may vary
        # but content should be equal
        assert updated_chunk.content == original_string

        # Verify metadata was updated
        assert updated_chunk.metadata["new_meta"] == "new_data"
        assert original_chunk.metadata["meta"] == "data"  # Original unchanged

    def test_multiple_metadata_merges_preserve_originals(self):
        """
        Verify that multiple metadata merges preserve all original chunks.
        """
        original_chunk = ProcessedResponse(content="test", metadata={"key1": "value1"})

        # First merge
        metadata1 = dict(original_chunk.metadata)
        metadata1["key2"] = "value2"
        chunk1 = ProcessedResponse(
            content=original_chunk.content,
            metadata=metadata1,
            usage=original_chunk.usage,
        )

        # Second merge
        metadata2 = dict(chunk1.metadata)
        metadata2["key3"] = "value3"
        chunk2 = ProcessedResponse(
            content=chunk1.content, metadata=metadata2, usage=chunk1.usage
        )

        # Verify all chunks are distinct
        assert id(original_chunk) != id(chunk1)
        assert id(chunk1) != id(chunk2)
        assert id(original_chunk) != id(chunk2)

        # Verify original chunk is unchanged
        assert original_chunk.metadata == {"key1": "value1"}
        assert "key2" not in original_chunk.metadata
        assert "key3" not in original_chunk.metadata

        # Verify intermediate chunk
        assert chunk1.metadata["key1"] == "value1"
        assert chunk1.metadata["key2"] == "value2"
        assert "key3" not in chunk1.metadata

        # Verify final chunk
        assert chunk2.metadata["key1"] == "value1"
        assert chunk2.metadata["key2"] == "value2"
        assert chunk2.metadata["key3"] == "value3"

    def test_metadata_dict_not_shared_between_instances(self):
        """
        Verify that metadata dicts are not shared between ProcessedResponse instances.

        Each ProcessedResponse should have its own metadata dict instance.
        """
        shared_metadata_template = {"key": "value"}

        chunk1 = ProcessedResponse(
            content="test1", metadata=dict(shared_metadata_template)
        )
        chunk2 = ProcessedResponse(
            content="test2", metadata=dict(shared_metadata_template)
        )

        # Verify they have different metadata dict instances
        assert id(chunk1.metadata) != id(chunk2.metadata)

        # Modify one metadata
        chunk1.metadata["new_key"] = "new_value"

        # Verify other chunk is unaffected
        assert "new_key" not in chunk2.metadata
        assert chunk2.metadata == shared_metadata_template

    def test_content_sharing_for_large_payloads(self):
        """
        Verify that large content payloads are shared (not copied) when creating
        new ProcessedResponse instances with updated metadata.

        NFR1.1: Avoid deep-copy behavior for large payloads.
        """
        # Create a large dict payload
        large_dict = {"data": "x" * (1024 * 1024), "nested": {"key": "value"}}
        original_chunk = ProcessedResponse(
            content=large_dict, metadata={"meta": "data"}
        )

        # Store original dict identity
        original_dict_id = id(original_chunk.content)

        # Create new chunk with updated metadata
        updated_metadata = dict(original_chunk.metadata)
        updated_metadata["new_meta"] = "new_data"
        updated_chunk = ProcessedResponse(
            content=original_chunk.content,
            metadata=updated_metadata,
            usage=original_chunk.usage,
        )

        # Verify large dict is shared (not copied) - same object identity
        assert id(updated_chunk.content) == original_dict_id

        # Verify content is unchanged
        assert updated_chunk.content == large_dict
        assert original_chunk.content == large_dict
