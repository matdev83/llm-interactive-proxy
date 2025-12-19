"""Tests for BackendTarget canonical contract.

This module tests the BackendTarget value object which represents
a canonical backend target with backend, model, and URI parameters.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from pydantic.types import JsonValue
from src.core.domain.backend_target import BackendTarget
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget


class TestBackendTarget:
    """Test BackendTarget value object."""

    def test_backend_target_creation_with_empty_uri_params(self) -> None:
        """Test BackendTarget creation with empty URI params."""
        target = BackendTarget(
            backend="openai",
            model="gpt-4",
            uri_params={},
        )
        assert target.backend == "openai"
        assert target.model == "gpt-4"
        assert target.uri_params == {}
        assert isinstance(target.uri_params, dict)

    def test_backend_target_creation_with_uri_params(self) -> None:
        """Test BackendTarget creation with URI params."""
        uri_params: dict[str, JsonValue] = {
            "temperature": 0.5,
            "top_p": 0.9,
            "top_k": 40,
        }
        target = BackendTarget(
            backend="anthropic",
            model="claude-3-5-sonnet",
            uri_params=uri_params,
        )
        assert target.backend == "anthropic"
        assert target.model == "claude-3-5-sonnet"
        assert target.uri_params == uri_params
        assert target.uri_params["temperature"] == 0.5

    def test_backend_target_immutability(self) -> None:
        """Test that BackendTarget is immutable."""
        target = BackendTarget(
            backend="openai",
            model="gpt-4",
            uri_params={"temperature": 0.5},
        )
        with pytest.raises((TypeError, ValidationError)):
            target.backend = "anthropic"  # type: ignore[misc]

    def test_backend_target_equality(self) -> None:
        """Test BackendTarget equality comparison."""
        target1 = BackendTarget(
            backend="openai",
            model="gpt-4",
            uri_params={"temperature": 0.5},
        )
        target2 = BackendTarget(
            backend="openai",
            model="gpt-4",
            uri_params={"temperature": 0.5},
        )
        target3 = BackendTarget(
            backend="openai",
            model="gpt-4",
            uri_params={"temperature": 0.7},
        )
        assert target1.equals(target2)
        assert not target1.equals(target3)

    def test_backend_target_from_resolved_target(self) -> None:
        """Test conversion from ResolvedTarget to BackendTarget."""
        resolved = ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params={"temperature": 0.5, "top_p": 0.9},
        )
        target = BackendTarget.from_resolved_target(resolved)
        assert target.backend == "openai"
        assert target.model == "gpt-4"
        assert target.uri_params == {"temperature": 0.5, "top_p": 0.9}

    def test_backend_target_to_resolved_target(self) -> None:
        """Test conversion from BackendTarget to ResolvedTarget."""
        target = BackendTarget(
            backend="anthropic",
            model="claude-3-5-sonnet",
            uri_params={"temperature": 0.7},
        )
        resolved = target.to_resolved_target()
        assert resolved.backend == "anthropic"
        assert resolved.model == "claude-3-5-sonnet"
        assert resolved.uri_params == {"temperature": 0.7}
        assert isinstance(resolved, ResolvedTarget)

    def test_backend_target_round_trip_conversion(self) -> None:
        """Test round-trip conversion between ResolvedTarget and BackendTarget."""
        original = ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params={"temperature": 0.5, "top_k": 40},
        )
        target = BackendTarget.from_resolved_target(original)
        converted_back = target.to_resolved_target()
        assert converted_back.backend == original.backend
        assert converted_back.model == original.model
        assert converted_back.uri_params == original.uri_params

    def test_backend_target_json_serialization(self) -> None:
        """Test that BackendTarget can be serialized to JSON."""
        target = BackendTarget(
            backend="openai",
            model="gpt-4",
            uri_params={"temperature": 0.5, "top_k": 40},
        )
        # Should be able to serialize URI params
        json_str = json.dumps(target.uri_params)
        assert json_str is not None
        deserialized = json.loads(json_str)
        assert deserialized == target.uri_params

    def test_backend_target_from_dict(self) -> None:
        """Test creating BackendTarget from dictionary."""
        data = {
            "backend": "openai",
            "model": "gpt-4",
            "uri_params": {"temperature": 0.5},
        }
        target = BackendTarget.from_dict(data)
        assert target.backend == "openai"
        assert target.model == "gpt-4"
        assert target.uri_params == {"temperature": 0.5}

    def test_backend_target_to_dict(self) -> None:
        """Test converting BackendTarget to dictionary."""
        target = BackendTarget(
            backend="anthropic",
            model="claude-3-5-sonnet",
            uri_params={"temperature": 0.7},
        )
        data = target.to_dict()
        assert data["backend"] == "anthropic"
        assert data["model"] == "claude-3-5-sonnet"
        assert data["uri_params"] == {"temperature": 0.7}
