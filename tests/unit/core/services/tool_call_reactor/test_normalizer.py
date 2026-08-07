"""Tests for ToolCallNormalizer.

Following TDD methodology: tests written before implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

from pydantic import BaseModel
from src.core.interfaces.tool_call_normalizer_interface import IToolCallNormalizer
from src.core.services.tool_call_reactor.normalizer import ToolCallNormalizer


class TestNormalizeDict:
    """Tests for normalization of dictionary objects."""

    def test_normalize_dict_object(self) -> None:
        """Test that dict objects are returned as-is."""
        normalizer = ToolCallNormalizer()
        tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }

        result = normalizer.normalize(tool_call)

        assert result == tool_call
        assert isinstance(result, dict)

    def test_normalize_empty_dict(self) -> None:
        """Test that empty dict is returned as-is."""
        normalizer = ToolCallNormalizer()
        tool_call = {}

        result = normalizer.normalize(tool_call)

        assert result == {}

    def test_normalize_dict_with_nested_structure(self) -> None:
        """Test that nested dict structures are preserved."""
        normalizer = ToolCallNormalizer()
        tool_call = {
            "id": "call_1",
            "function": {
                "name": "test_tool",
                "arguments": '{"key": "value", "nested": {"inner": 123}}',
            },
            "type": "function",
        }

        result = normalizer.normalize(tool_call)

        assert result == tool_call
        assert (
            result["function"]["arguments"]
            == '{"key": "value", "nested": {"inner": 123}}'
        )


class TestNormalizePydanticModel:
    """Tests for normalization of Pydantic models."""

    def test_normalize_pydantic_model(self) -> None:
        """Test that Pydantic models are converted using model_dump()."""
        normalizer = ToolCallNormalizer()

        class ToolCallModel(BaseModel):
            id: str
            function: dict[str, str]

            class Config:
                extra = "allow"

        tool_call = ToolCallModel(
            id="call_1", function={"name": "test_tool", "arguments": "{}"}
        )

        result = normalizer.normalize(tool_call)

        assert isinstance(result, dict)
        assert result["id"] == "call_1"
        assert result["function"] == {"name": "test_tool", "arguments": "{}"}

    def test_normalize_pydantic_model_with_extra_fields(self) -> None:
        """Test that Pydantic models with extra fields are normalized correctly."""
        normalizer = ToolCallNormalizer()

        class ToolCallModel(BaseModel):
            id: str
            function: dict[str, str]

            class Config:
                extra = "allow"

        tool_call = ToolCallModel(
            id="call_1",
            function={"name": "test_tool", "arguments": "{}"},
            extra_field="extra_value",
        )

        result = normalizer.normalize(tool_call)

        assert isinstance(result, dict)
        assert result["id"] == "call_1"
        assert result.get("extra_field") == "extra_value"

    def test_normalize_pydantic_model_dump_returns_non_dict(self) -> None:
        """Test that Pydantic model returning non-dict from model_dump() returns None."""
        normalizer = ToolCallNormalizer()

        class BadModel(BaseModel):
            def model_dump(self) -> str:  # type: ignore[override]
                return "not a dict"

        tool_call = BadModel()

        result = normalizer.normalize(tool_call)

        assert result is None

    def test_normalize_pydantic_model_dump_exception(self) -> None:
        """Test that exceptions during model_dump() are handled gracefully."""
        from typing import Any

        normalizer = ToolCallNormalizer()

        class BadModel(BaseModel):
            def model_dump(self) -> dict[str, Any]:  # type: ignore[override]
                raise ValueError("model_dump failed")

        tool_call = BadModel()

        result = normalizer.normalize(tool_call)

        assert result is None


class TestNormalizeDataclass:
    """Tests for normalization of dataclass instances."""

    def test_normalize_dataclass(self) -> None:
        """Test that dataclass instances are converted using asdict()."""
        normalizer = ToolCallNormalizer()

        @dataclass
        class ToolCallDataclass:
            id: str
            function: dict[str, str]

        tool_call = ToolCallDataclass(
            id="call_1", function={"name": "test_tool", "arguments": "{}"}
        )

        result = normalizer.normalize(tool_call)

        assert isinstance(result, dict)
        assert result["id"] == "call_1"
        assert result["function"] == {"name": "test_tool", "arguments": "{}"}

    def test_normalize_dataclass_with_nested_dataclass(self) -> None:
        """Test that nested dataclasses are normalized correctly."""
        normalizer = ToolCallNormalizer()

        @dataclass
        class FunctionCall:
            name: str
            arguments: str

        @dataclass
        class ToolCallDataclass:
            id: str
            function: FunctionCall

        tool_call = ToolCallDataclass(
            id="call_1", function=FunctionCall(name="test_tool", arguments="{}")
        )

        result = normalizer.normalize(tool_call)

        assert isinstance(result, dict)
        assert result["id"] == "call_1"
        assert isinstance(result["function"], dict)
        assert result["function"]["name"] == "test_tool"

    def test_normalize_dataclass_asdict_exception(self) -> None:
        """Test that exceptions during asdict() are handled gracefully."""
        normalizer = ToolCallNormalizer()

        # Create a dataclass that will fail during asdict()
        # We'll use a mock to simulate this
        tool_call = Mock()
        tool_call.__class__.__name__ = "ToolCallDataclass"
        # Make is_dataclass return True but asdict fail
        import dataclasses

        original_is_dataclass = dataclasses.is_dataclass
        dataclasses.is_dataclass = lambda obj: obj is tool_call  # type: ignore[assignment]
        original_asdict = dataclasses.asdict
        dataclasses.asdict = lambda obj: (_ for _ in ()).throw(ValueError("asdict failed"))  # type: ignore[assignment]

        try:
            result = normalizer.normalize(tool_call)
            assert result is None
        finally:
            dataclasses.is_dataclass = original_is_dataclass
            dataclasses.asdict = original_asdict


class TestSkipUnnormalizable:
    """Tests for skip behavior with un-normalizable objects."""

    def test_normalize_none(self) -> None:
        """Test that None returns None."""
        normalizer = ToolCallNormalizer()

        result = normalizer.normalize(None)

        assert result is None

    def test_normalize_string(self) -> None:
        """Test that string objects return None."""
        normalizer = ToolCallNormalizer()

        result = normalizer.normalize("not a tool call")

        assert result is None

    def test_normalize_int(self) -> None:
        """Test that integer objects return None."""
        normalizer = ToolCallNormalizer()

        result = normalizer.normalize(12345)

        assert result is None

    def test_normalize_list(self) -> None:
        """Test that list objects return None."""
        normalizer = ToolCallNormalizer()

        result = normalizer.normalize([1, 2, 3])

        assert result is None

    def test_normalize_object_without_model_dump_or_dataclass(self) -> None:
        """Test that regular objects without model_dump or dataclass return None."""
        normalizer = ToolCallNormalizer()

        class RegularClass:
            def __init__(self) -> None:
                self.id = "call_1"

        tool_call = RegularClass()

        result = normalizer.normalize(tool_call)

        assert result is None

    def test_normalize_dataclass_type_not_instance(self) -> None:
        """Test that dataclass type (not instance) returns None."""
        normalizer = ToolCallNormalizer()

        @dataclass
        class ToolCallDataclass:
            id: str

        # Pass the class itself, not an instance
        result = normalizer.normalize(ToolCallDataclass)

        assert result is None


class TestFailOpenBehavior:
    """Tests for fail-open behavior (exceptions don't crash)."""

    def test_exception_during_normalization(self) -> None:
        """Test that exceptions during normalization are handled gracefully."""
        normalizer = ToolCallNormalizer()

        # Create an object that will raise an exception when accessed
        tool_call = Mock()
        tool_call.__class__ = type(
            "BadClass",
            (),
            {
                "__getattribute__": lambda self, name: (_ for _ in ()).throw(
                    RuntimeError("access error")
                )
            },
        )

        result = normalizer.normalize(tool_call)

        assert result is None


class TestInterfaceCompliance:
    """Tests for interface compliance."""

    def test_implements_interface(self) -> None:
        """Test that ToolCallNormalizer implements IToolCallNormalizer."""
        normalizer = ToolCallNormalizer()
        assert isinstance(normalizer, IToolCallNormalizer)
