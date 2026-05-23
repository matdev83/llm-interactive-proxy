"""Tests for UsageSummary canonical contract.

This module tests the UsageSummary value object which represents
a canonical usage summary with token counts and provider-specific extensions.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from pydantic.types import JsonValue
from src.core.domain.usage_summary import UsageSummary


class TestUsageSummary:
    """Test UsageSummary value object."""

    def test_usage_summary_creation_with_all_fields(self) -> None:
        """Test UsageSummary creation with all fields."""
        summary = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={"cost": 0.002},
        )
        assert summary.prompt_tokens == 100
        assert summary.completion_tokens == 50
        assert summary.total_tokens == 150
        assert summary.extensions == {"cost": 0.002}

    def test_usage_summary_creation_with_none_fields(self) -> None:
        """Test UsageSummary creation with None fields."""
        summary = UsageSummary(
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            extensions={},
        )
        assert summary.prompt_tokens is None
        assert summary.completion_tokens is None
        assert summary.total_tokens is None
        assert summary.extensions == {}

    def test_usage_summary_creation_with_partial_fields(self) -> None:
        """Test UsageSummary creation with partial fields."""
        summary = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=None,
            extensions={},
        )
        assert summary.prompt_tokens == 100
        assert summary.completion_tokens == 50
        assert summary.total_tokens is None

    def test_usage_summary_immutability(self) -> None:
        """Test that UsageSummary is immutable."""
        summary = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={},
        )
        with pytest.raises((TypeError, ValidationError)):
            summary.prompt_tokens = 200  # type: ignore[misc]

    def test_usage_summary_equality(self) -> None:
        """Test UsageSummary equality comparison."""
        summary1 = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={"cost": 0.002},
        )
        summary2 = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={"cost": 0.002},
        )
        summary3 = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={"cost": 0.003},
        )
        assert summary1.equals(summary2)
        assert not summary1.equals(summary3)

    def test_usage_summary_from_dict(self) -> None:
        """Test creating UsageSummary from dictionary."""
        data = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "extensions": {"cost": 0.002},
        }
        summary = UsageSummary.from_dict(data)
        assert summary.prompt_tokens == 100
        assert summary.completion_tokens == 50
        assert summary.total_tokens == 150
        assert summary.extensions == {"cost": 0.002}

    def test_usage_summary_from_dict_with_none(self) -> None:
        """Test creating UsageSummary from dictionary with None values."""
        data: dict[str, object] = {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "extensions": {},
        }
        summary = UsageSummary.from_dict(data)
        assert summary.prompt_tokens is None
        assert summary.completion_tokens is None
        assert summary.total_tokens is None

    def test_usage_summary_to_dict(self) -> None:
        """Test converting UsageSummary to dictionary."""
        summary = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={"cost": 0.002},
        )
        data = summary.to_dict()
        assert data["prompt_tokens"] == 100
        assert data["completion_tokens"] == 50
        assert data["total_tokens"] == 150
        assert data["extensions"] == {"cost": 0.002}

    def test_usage_summary_merge(self) -> None:
        """Test merging two UsageSummary instances."""
        summary1 = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={"cost": 0.002},
        )
        summary2 = UsageSummary(
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            extensions={"cost": 0.004, "requests": 2},
        )
        merged = summary1.merge(summary2)
        assert merged.prompt_tokens == 300  # 100 + 200
        assert merged.completion_tokens == 150  # 50 + 100
        assert merged.total_tokens == 450  # 150 + 300
        assert merged.extensions == {
            "cost": 0.006,  # 0.002 + 0.004
            "requests": 2,
        }

    def test_usage_summary_merge_with_none(self) -> None:
        """Test merging UsageSummary instances with None values."""
        summary1 = UsageSummary(
            prompt_tokens=100,
            completion_tokens=None,
            total_tokens=None,
            extensions={},
        )
        summary2 = UsageSummary(
            prompt_tokens=200,
            completion_tokens=50,
            total_tokens=250,
            extensions={},
        )
        merged = summary1.merge(summary2)
        assert merged.prompt_tokens == 300
        assert merged.completion_tokens == 50  # None + 50 = 50
        assert merged.total_tokens == 250  # None + 250 = 250

    def test_usage_summary_json_serialization(self) -> None:
        """Test that UsageSummary can be serialized to JSON."""
        summary = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions={"cost": 0.002, "provider": "openai"},
        )
        # Should be able to serialize to JSON
        data = summary.to_dict()
        json_str = json.dumps(data)
        assert json_str is not None
        deserialized = json.loads(json_str)
        assert deserialized["prompt_tokens"] == 100
        assert deserialized["completion_tokens"] == 50
        assert deserialized["total_tokens"] == 150
        assert deserialized["extensions"] == {"cost": 0.002, "provider": "openai"}

    def test_usage_summary_extensions_json_serializable(self) -> None:
        """Test that UsageSummary extensions are JSON-serializable."""
        extensions: dict[str, JsonValue] = {
            "cost": 0.002,
            "requests": 1,
            "provider": "openai",
            "enabled": True,
            "optional": None,
        }
        summary = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            extensions=extensions,
        )
        # Should be able to serialize extensions to JSON
        json_str = json.dumps(summary.extensions)
        assert json_str is not None
        deserialized = json.loads(json_str)
        assert deserialized == extensions
