"""Tests for backend model resolver interface and ResolvedTarget."""

from __future__ import annotations

from pydantic.types import JsonValue
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget


class TestResolvedTarget:
    """Tests for ResolvedTarget typed contract."""

    def test_resolved_target_with_empty_uri_params(self) -> None:
        """Test ResolvedTarget creation with empty URI params."""
        target = ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params={},
        )
        assert target.backend == "openai"
        assert target.model == "gpt-4"
        assert target.uri_params == {}
        assert isinstance(target.uri_params, dict)

    def test_resolved_target_with_string_uri_params(self) -> None:
        """Test ResolvedTarget creation with string URI params (from query parsing)."""
        uri_params: dict[str, JsonValue] = {
            "temperature": "0.5",
            "reasoning_effort": "low",
        }
        target = ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params=uri_params,
        )
        assert target.backend == "openai"
        assert target.model == "gpt-4"
        assert target.uri_params == uri_params
        assert target.uri_params["temperature"] == "0.5"
        assert target.uri_params["reasoning_effort"] == "low"

    def test_resolved_target_with_numeric_uri_params(self) -> None:
        """Test ResolvedTarget creation with numeric URI params (after coercion)."""
        uri_params: dict[str, JsonValue] = {
            "temperature": 0.5,
            "top_p": 0.9,
            "top_k": 40,
        }
        target = ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params=uri_params,
        )
        assert target.backend == "openai"
        assert target.model == "gpt-4"
        assert target.uri_params == uri_params
        assert target.uri_params["temperature"] == 0.5
        assert target.uri_params["top_p"] == 0.9
        assert target.uri_params["top_k"] == 40

    def test_resolved_target_with_mixed_json_value_types(self) -> None:
        """Test ResolvedTarget creation with mixed JSON-serializable types."""
        uri_params: dict[str, JsonValue] = {
            "temperature": 0.5,  # float
            "top_k": 40,  # int
            "reasoning_effort": "low",  # str
            "enabled": True,  # bool
            "optional": None,  # None
        }
        target = ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params=uri_params,
        )
        assert target.backend == "openai"
        assert target.model == "gpt-4"
        assert target.uri_params == uri_params
        assert isinstance(target.uri_params["temperature"], float)
        assert isinstance(target.uri_params["top_k"], int)
        assert isinstance(target.uri_params["reasoning_effort"], str)
        assert isinstance(target.uri_params["enabled"], bool)
        assert target.uri_params["optional"] is None

    def test_resolved_target_uri_params_are_json_serializable(self) -> None:
        """Test that ResolvedTarget URI params are JSON-serializable."""
        import json

        uri_params: dict[str, JsonValue] = {
            "temperature": 0.5,
            "top_k": 40,
            "reasoning_effort": "low",
            "enabled": True,
            "optional": None,
        }
        target = ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params=uri_params,
        )
        # Should be able to serialize to JSON without errors
        json_str = json.dumps(target.uri_params)
        assert json_str is not None
        # Should be able to deserialize back
        deserialized = json.loads(json_str)
        assert deserialized == uri_params
