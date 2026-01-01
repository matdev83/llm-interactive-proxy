"""Tests for chunk normalizer utility."""

from __future__ import annotations

from typing import Any

from src.core.services.streaming.chunk_normalizer import (
    normalize_to_processed_chunk_content,
)


class TestNormalizeToProcessedChunkContent:
    """Test normalization of various input types to ProcessedChunkContent."""

    def test_normalize_none(self) -> None:
        """Test that None is preserved."""
        result = normalize_to_processed_chunk_content(None)
        assert result is None
        assert isinstance(result, type(None))

    def test_normalize_str(self) -> None:
        """Test that str is preserved."""
        content = "test content"
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, str)

    def test_normalize_bytes(self) -> None:
        """Test that bytes are preserved."""
        content = b"test bytes"
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, bytes)

    def test_normalize_bytearray(self) -> None:
        """Test that bytearray is converted to bytes."""
        content = bytearray(b"test bytearray")
        result = normalize_to_processed_chunk_content(content)
        assert result == b"test bytearray"
        assert isinstance(result, bytes)

    def test_normalize_json_safe_dict(self) -> None:
        """Test that JSON-safe dicts are preserved."""
        content = {"key": "value", "number": 42, "bool": True, "null": None}
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, dict)
        # Verify all values are JsonValue-compatible
        assert all(isinstance(v, str | int | float | bool | type(None)) for v in result.values())

    def test_normalize_dict_with_nested_json_safe(self) -> None:
        """Test that nested JSON-safe dicts are preserved."""
        content = {
            "key": "value",
            "nested": {"inner": "value", "number": 42},
            "list": [1, 2, 3],
        }
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, dict)

    def test_normalize_dict_with_non_json_serializable_values(self) -> None:
        """Test that dicts with non-JSON-serializable values are sanitized."""
        # Create a dict with a callable (not JSON-serializable)
        def some_function() -> None:
            pass

        content = {"key": "value", "callable": some_function}
        result = normalize_to_processed_chunk_content(content)
        assert isinstance(result, dict)
        # The callable should be removed or converted
        assert "key" in result
        assert result["key"] == "value"
        # Callable should not be present (sanitized out)
        assert "callable" not in result

    def test_normalize_dict_with_complex_object(self) -> None:
        """Test that dicts with complex objects are sanitized."""
        class ComplexObject:
            def __init__(self) -> None:
                self.value = "test"

        content = {"key": "value", "complex": ComplexObject()}
        result = normalize_to_processed_chunk_content(content)
        assert isinstance(result, dict)
        assert "key" in result
        assert result["key"] == "value"
        # Complex object should be removed
        assert "complex" not in result

    def test_normalize_provider_specific_dict(self) -> None:
        """Test that provider-specific dicts are normalized to JSON-safe dicts."""
        # Simulate a provider-specific dict (e.g., OpenAI chunk format)
        content = {
            "choices": [
                {
                    "delta": {"content": "test"},
                    "finish_reason": None,
                }
            ],
            "model": "gpt-4",
            "created": 1234567890,
        }
        result = normalize_to_processed_chunk_content(content)
        assert isinstance(result, dict)
        assert result == content  # Should be preserved as-is since it's JSON-safe

    def test_normalize_list_to_str(self) -> None:
        """Test that lists are converted to string representation."""
        content = [1, 2, 3]
        result = normalize_to_processed_chunk_content(content)
        assert isinstance(result, str)
        assert result == "[1, 2, 3]"

    def test_normalize_tuple_to_str(self) -> None:
        """Test that tuples are converted to string representation."""
        content = (1, 2, 3)
        result = normalize_to_processed_chunk_content(content)
        assert isinstance(result, str)
        assert result == "(1, 2, 3)"

    def test_normalize_complex_object_to_str(self) -> None:
        """Test that complex objects are converted to string."""
        class CustomObject:
            def __init__(self) -> None:
                self.value = "test"

            def __str__(self) -> str:
                return f"CustomObject(value={self.value})"

        content = CustomObject()
        result = normalize_to_processed_chunk_content(content)
        assert isinstance(result, str)
        assert "CustomObject" in result

    def test_normalize_dict_preserves_shallow_copy_semantics(self) -> None:
        """Test that dict normalization preserves shallow copy semantics (no deep copy)."""
        original = {"key": "value", "nested": {"inner": "value"}}
        result = normalize_to_processed_chunk_content(original)
        
        # Should be a new dict (shallow copy)
        assert result is not original
        # But nested dict should be the same object (shallow copy)
        assert isinstance(result, dict)
        assert "nested" in result
        assert isinstance(result["nested"], dict)
        assert result["nested"] is original["nested"]

    def test_normalize_dict_with_empty_dict(self) -> None:
        """Test that empty dicts are preserved."""
        content: dict[str, Any] = {}
        result = normalize_to_processed_chunk_content(content)
        assert result == {}
        assert isinstance(result, dict)

    def test_normalize_dict_with_empty_string(self) -> None:
        """Test that empty strings are preserved."""
        content = ""
        result = normalize_to_processed_chunk_content(content)
        assert result == ""
        assert isinstance(result, str)

    def test_normalize_dict_with_empty_bytes(self) -> None:
        """Test that empty bytes are preserved."""
        content = b""
        result = normalize_to_processed_chunk_content(content)
        assert result == b""
        assert isinstance(result, bytes)

    def test_normalize_dict_with_unicode_string(self) -> None:
        """Test that unicode strings are preserved."""
        content = "测试内容 🚀"
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, str)

    def test_normalize_dict_with_unicode_bytes(self) -> None:
        """Test that unicode bytes are preserved."""
        content = "测试内容 🚀".encode()
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, bytes)

    def test_normalize_dict_with_float_values(self) -> None:
        """Test that dicts with float values are preserved."""
        content = {"pi": 3.14159, "e": 2.71828}
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, dict)

    def test_normalize_dict_with_boolean_values(self) -> None:
        """Test that dicts with boolean values are preserved."""
        content = {"true": True, "false": False}
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, dict)

    def test_normalize_dict_with_none_values(self) -> None:
        """Test that dicts with None values are preserved."""
        content = {"key1": None, "key2": "value"}
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, dict)

    def test_normalize_dict_with_list_values(self) -> None:
        """Test that dicts with list values are preserved if JSON-safe."""
        content = {"items": [1, 2, 3], "nested": [{"a": 1}, {"b": 2}]}
        result = normalize_to_processed_chunk_content(content)
        assert result == content
        assert isinstance(result, dict)

    def test_normalize_dict_with_circular_reference_handled(self) -> None:
        """Test that dicts with circular references are handled gracefully."""
        content: dict[str, Any] = {"key": "value"}
        content["self"] = content  # Create circular reference
        
        # Should not raise an error, but should handle gracefully
        result = normalize_to_processed_chunk_content(content)
        # The circular reference should be sanitized out
        assert isinstance(result, dict)
        assert "key" in result
        assert result["key"] == "value"
