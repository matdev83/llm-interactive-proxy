"""Unit tests for ParameterApplicator service.

Tests cover applying phase-specific parameters to various request data types.

Requirements satisfied:
- Req 2.2: ParameterApplicator extraction
- Req 11: Test-preserving migration
"""

from dataclasses import dataclass
from unittest.mock import patch

import pytest
from src.connectors.hybrid_backend.protocols import IParameterApplicator
from src.core.domain.chat import ChatRequest
from src.core.interfaces.model_bases import DomainModel


class TestParameterApplicator:
    """Test ParameterApplicator service implementation."""

    @pytest.fixture
    def applicator(self):
        """Create a ParameterApplicator instance for testing."""
        from src.connectors.hybrid_backend.services.parameter_applicator import (
            ParameterApplicator,
        )

        return ParameterApplicator()

    def test_applicator_implements_protocol(self, applicator):
        """Verify applicator implements IParameterApplicator protocol."""
        assert isinstance(applicator, IParameterApplicator)

    def test_apply_reasoning_params_pydantic_model(self, applicator):
        """Test apply_reasoning_params() with Pydantic model."""
        from src.core.domain.chat import ChatMessage

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
            temperature=0.5,
        )

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_reasoning_params",
            return_value={"reasoning_effort": "high", "temperature": 0.7},
        ):
            result = applicator.apply_reasoning_params(request, "openai")

        assert isinstance(result, DomainModel)
        assert result.temperature == 0.7
        assert hasattr(result, "extra_body")
        if result.extra_body:
            assert result.extra_body.get("reasoning_effort") == "high"

    def test_apply_reasoning_params_dict(self, applicator):
        """Test apply_reasoning_params() with dict."""
        request = {"model": "test-model", "messages": [], "temperature": 0.5}

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_reasoning_params",
            return_value={"reasoning_effort": "high"},
        ):
            result = applicator.apply_reasoning_params(request, "openai")

        assert isinstance(result, dict)
        assert result["reasoning_effort"] == "high"
        assert "extra_body" in result
        if result["extra_body"]:
            assert result["extra_body"].get("reasoning_effort") == "high"

    def test_apply_reasoning_params_dict_with_extra_body(self, applicator):
        """Test apply_reasoning_params() with dict that has extra_body."""
        request = {
            "model": "test-model",
            "messages": [],
            "extra_body": {"existing": "value"},
        }

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_reasoning_params",
            return_value={"reasoning_effort": "high"},
        ):
            result = applicator.apply_reasoning_params(request, "openai")

        assert isinstance(result, dict)
        assert result["extra_body"]["existing"] == "value"
        assert result["extra_body"]["reasoning_effort"] == "high"

    def test_apply_reasoning_params_dataclass(self, applicator):
        """Test apply_reasoning_params() with dataclass."""

        @dataclass
        class TestRequest:
            model: str
            messages: list
            temperature: float = 0.5

        request = TestRequest(model="test-model", messages=[])

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_reasoning_params",
            return_value={"reasoning_effort": "high"},
        ):
            result = applicator.apply_reasoning_params(request, "openai")

        # Dataclass is converted to dict
        assert isinstance(result, dict)
        assert result["reasoning_effort"] == "high"

    def test_apply_reasoning_params_with_uri_overrides(self, applicator):
        """Test apply_reasoning_params() with URI parameter overrides."""
        request = {"model": "test-model", "messages": []}

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_reasoning_params",
            return_value={"reasoning_effort": "high", "temperature": 0.7},
        ):
            result = applicator.apply_reasoning_params(
                request, "openai", params={"temperature": 0.9}
            )

        assert result["temperature"] == 0.9  # Override takes precedence
        assert result["extra_body"]["reasoning_effort"] == "high"

    def test_apply_reasoning_params_strips_routing_hints(self, applicator):
        """Test apply_reasoning_params() strips hybrid routing hints."""
        request = {
            "model": "test-model",
            "messages": [],
            "extra_body": {"backend_type": "hybrid", "model": "hybrid:..."},
        }

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_reasoning_params",
            return_value={"reasoning_effort": "high"},
        ):
            result = applicator.apply_reasoning_params(request, "openai")

        assert "backend_type" not in result["extra_body"]
        assert result["extra_body"].get("model") != "hybrid:..."

    def test_apply_execution_params_pydantic_model(self, applicator):
        """Test apply_execution_params() with Pydantic model."""
        from src.core.domain.chat import ChatMessage

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
            temperature=0.5,
        )

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_execution_params",
            return_value={"reasoning_effort": "low", "temperature": 0.3},
        ):
            result = applicator.apply_execution_params(request, "openai")

        assert isinstance(result, DomainModel)
        assert result.temperature == 0.3

    def test_apply_execution_params_dict(self, applicator):
        """Test apply_execution_params() with dict."""
        request = {"model": "test-model", "messages": [], "temperature": 0.5}

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_execution_params",
            return_value={"reasoning_effort": "low"},
        ):
            result = applicator.apply_execution_params(request, "openai")

        assert isinstance(result, dict)
        assert result["reasoning_effort"] == "low"

    def test_apply_execution_params_with_uri_overrides(self, applicator):
        """Test apply_execution_params() with URI parameter overrides."""
        request = {"model": "test-model", "messages": []}

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_execution_params",
            return_value={"reasoning_effort": "low", "temperature": 0.3},
        ):
            result = applicator.apply_execution_params(
                request, "openai", params={"temperature": 0.5}
            )

        assert result["temperature"] == 0.5  # Override takes precedence

    def test_apply_reasoning_params_empty_params(self, applicator):
        """Test apply_reasoning_params() with empty params returns original."""
        request = {"model": "test-model", "messages": []}

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_reasoning_params",
            return_value={},
        ):
            result = applicator.apply_reasoning_params(request, "openai")

        assert result == request

    def test_apply_execution_params_empty_params(self, applicator):
        """Test apply_execution_params() with empty params returns original."""
        request = {"model": "test-model", "messages": []}

        with patch(
            "src.connectors.hybrid_backend.services.parameter_applicator.get_execution_params",
            return_value={},
        ):
            result = applicator.apply_execution_params(request, "openai")

        assert result == request
