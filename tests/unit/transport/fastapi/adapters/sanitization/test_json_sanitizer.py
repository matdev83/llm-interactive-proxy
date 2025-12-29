"""Tests for JSONSanitizer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from src.core.services.steering_leak_protection import (
    DictSanitizationResult,
    SteeringLeakProtector,
)
from src.core.transport.fastapi.adapters.sanitization.json_sanitizer import (
    JSONSanitizer,
)


class TestJSONSanitizer:
    """Test JSONSanitizer implementation."""

    def test_coroutine_conversion_to_string(self):
        """Test that coroutines are converted to strings."""
        sanitizer = JSONSanitizer()

        async def coro():
            return "test"

        coroutine_obj = coro()
        result = sanitizer.sanitize(coroutine_obj)
        assert isinstance(result, str)
        coroutine_obj.close()  # Clean up

    def test_asyncmock_conversion_to_string(self):
        """Test that AsyncMock objects are converted to strings."""
        sanitizer = JSONSanitizer()
        mock_obj = AsyncMock()
        result = sanitizer.sanitize(mock_obj)
        assert isinstance(result, str)

    def test_nested_object_sanitization(self):
        """Test that nested objects are sanitized recursively."""
        sanitizer = JSONSanitizer()

        async def coro():
            return "test"

        coroutine_obj = coro()
        nested = {
            "level1": {
                "level2": [coroutine_obj, "string"],
                "mock": AsyncMock(),
            },
            "simple": "value",
        }
        result = sanitizer.sanitize(nested)
        assert isinstance(result, dict)
        assert result["level1"]["level2"][0] == str(coroutine_obj)
        assert isinstance(result["level1"]["level2"][0], str)
        assert result["level1"]["level2"][1] == "string"
        assert isinstance(result["level1"]["mock"], str)
        assert result["simple"] == "value"
        coroutine_obj.close()  # Clean up

    def test_list_sanitization(self):
        """Test that lists are sanitized recursively."""
        sanitizer = JSONSanitizer()

        async def coro():
            return "test"

        coroutine_obj = coro()
        test_list = [coroutine_obj, {"nested": AsyncMock()}, "string"]
        result = sanitizer.sanitize(test_list)
        assert isinstance(result, list)
        assert isinstance(result[0], str)
        assert isinstance(result[1], dict)
        assert isinstance(result[1]["nested"], str)
        assert result[2] == "string"
        coroutine_obj.close()  # Clean up

    def test_tuple_sanitization(self):
        """Test that tuples are sanitized recursively."""
        sanitizer = JSONSanitizer()

        async def coro():
            return "test"

        coroutine_obj = coro()
        test_tuple = (coroutine_obj, "string")
        result = sanitizer.sanitize(test_tuple)
        assert isinstance(result, tuple)
        assert isinstance(result[0], str)
        assert result[1] == "string"
        coroutine_obj.close()  # Clean up

    def test_steering_leak_detection_logging(self):
        """Test that steering leak detection logs security warnings."""
        mock_protector = MagicMock(spec=SteeringLeakProtector)
        mock_protector.enabled = True
        mock_protector.sanitize_dict.return_value = DictSanitizationResult(
            data={"safe": "content"}, had_leak=True
        )

        sanitizer = JSONSanitizer(protector=mock_protector)
        content = {"steering_message": "leaked", "normal": "data"}

        result = sanitizer.sanitize(content)

        mock_protector.sanitize_dict.assert_called_once()
        assert result == {"safe": "content"}

    def test_di_injection_works(self):
        """Test that DI injection works via constructor."""
        mock_protector = MagicMock(spec=SteeringLeakProtector)
        mock_protector.enabled = True
        mock_protector.sanitize_dict.return_value = DictSanitizationResult(
            data={"test": "data"}, had_leak=False
        )

        sanitizer = JSONSanitizer(protector=mock_protector)
        result = sanitizer.sanitize({"test": "data"})

        mock_protector.sanitize_dict.assert_called_once()
        assert result == {"test": "data"}

    def test_fallback_to_global_accessor(self):
        """Test that fallback to global accessor works when not provided."""
        sanitizer = JSONSanitizer()
        # Should not raise error even without explicit protector
        result = sanitizer.sanitize({"test": "data"})
        assert result == {"test": "data"}

    def test_none_handling(self):
        """Test that None is handled correctly."""
        sanitizer = JSONSanitizer()
        result = sanitizer.sanitize(None)
        assert result is None

    def test_serializable_objects_preserved(self):
        """Test that serializable objects are preserved."""
        sanitizer = JSONSanitizer()
        content = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }
        result = sanitizer.sanitize(content)
        assert result == content
        # Verify it's JSON serializable
        json.dumps(result)

    def test_non_serializable_converted_to_string(self):
        """Test that non-serializable objects are converted to strings."""
        sanitizer = JSONSanitizer()

        class NonSerializable:
            def __str__(self):
                return "NonSerializable"

        obj = NonSerializable()
        result = sanitizer.sanitize(obj)
        assert isinstance(result, str)
        assert result == "NonSerializable"

    def test_protector_disabled_no_check(self):
        """Test that protector is not called when disabled."""
        mock_protector = MagicMock(spec=SteeringLeakProtector)
        mock_protector.enabled = False

        sanitizer = JSONSanitizer(protector=mock_protector)
        content = {"test": "data"}
        result = sanitizer.sanitize(content)

        mock_protector.sanitize_dict.assert_not_called()
        assert result == content

    def test_protector_only_for_dicts(self):
        """Test that protector is only applied to dict content."""
        mock_protector = MagicMock(spec=SteeringLeakProtector)
        mock_protector.enabled = True

        sanitizer = JSONSanitizer(protector=mock_protector)
        # Non-dict content should not trigger protector
        result = sanitizer.sanitize("string")
        mock_protector.sanitize_dict.assert_not_called()
        assert result == "string"
