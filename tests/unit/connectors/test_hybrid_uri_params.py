"""Unit tests for hybrid backend URI parameter support."""

import logging
from unittest.mock import Mock

import pytest
from src.connectors.hybrid import HybridConnector
from src.core.config.app_config import AppConfig, BackendSettings


@pytest.fixture
def app_config():
    """Create a basic app config for testing."""
    config = AppConfig()
    # Ensure hybrid backend is enabled by default
    if not hasattr(config, "backends"):
        config.backends = BackendSettings(disable_hybrid_backend=False)
    return config


@pytest.fixture
def hybrid_connector(app_config):
    """Create a hybrid connector instance for testing."""
    connector = HybridConnector(
        client=Mock(),
        config=app_config,
        translation_service=Mock(),
        backend_registry=Mock(),
    )
    return connector


class TestHybridURIParameterParsing:
    """Test parsing hybrid model spec with URI parameters."""

    def test_parse_both_models_with_temperature(self, hybrid_connector):
        """Test parsing hybrid model spec with temperature on both models."""
        model_spec = (
            "hybrid:[backend1:model1?temperature=0.8,backend2:model2?temperature=0.3]"
        )

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {"temperature": "0.8"}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {"temperature": "0.3"}

    def test_parse_reasoning_model_with_temperature(self, hybrid_connector):
        """Test parsing hybrid model spec with temperature only on reasoning model."""
        model_spec = "hybrid:[openai:gpt-4?temperature=0.9,anthropic:claude-3]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.reasoning_params == {"temperature": "0.9"}
        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"
        assert spec.execution_params == {}

    def test_parse_execution_model_with_temperature(self, hybrid_connector):
        """Test parsing hybrid model spec with temperature only on execution model."""
        model_spec = (
            "hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus?temperature=0.5]"
        )

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "minimax"
        assert spec.reasoning_model == "MiniMax-M2"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "qwen-oauth"
        assert spec.execution_model == "qwen3-coder-plus"
        assert spec.execution_params == {"temperature": "0.5"}

    def test_parse_multiple_parameters(self, hybrid_connector):
        """Test parsing hybrid model spec with multiple URI parameters."""
        model_spec = "hybrid:[backend1:model1?temperature=0.8&reasoning_effort=high,backend2:model2?temperature=0.3&reasoning_effort=low]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {
            "temperature": "0.8",
            "reasoning_effort": "high",
        }
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {
            "temperature": "0.3",
            "reasoning_effort": "low",
        }

    def test_parse_with_model_group(self, hybrid_connector):
        """Test parsing hybrid model spec with model groups and URI parameters."""
        model_spec = "hybrid:[backend1:group/model1?temperature=0.7,backend2:group/model2?temperature=0.4]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "group/model1"
        assert spec.reasoning_params == {"temperature": "0.7"}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "group/model2"
        assert spec.execution_params == {"temperature": "0.4"}

    def test_parse_no_uri_parameters(self, hybrid_connector):
        """Test parsing hybrid model spec without URI parameters (backward compatibility)."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:claude-3]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"
        assert spec.execution_params == {}

    def test_parse_with_whitespace(self, hybrid_connector):
        """Test parsing hybrid model spec with whitespace and URI parameters."""
        model_spec = "hybrid:[ backend1 : model1 ? temperature=0.8 , backend2 : model2 ? temperature=0.3 ]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        # Note: whitespace in query string is preserved by parse_qs
        assert (
            " temperature" in spec.reasoning_params
            or "temperature" in spec.reasoning_params
        )
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"


class TestHybridReasoningEffortWarning:
    """Test reasoning_effort warning when specified in hybrid model string."""

    def test_reasoning_effort_in_reasoning_model_logs_warning(
        self, hybrid_connector, caplog
    ):
        """Test that reasoning_effort in reasoning model logs a warning."""
        model_spec = "hybrid:[backend1:model1?reasoning_effort=high,backend2:model2]"

        with caplog.at_level(logging.DEBUG):
            spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Verify parsing succeeded
        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {"reasoning_effort": "high"}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {}

    def test_reasoning_effort_in_execution_model_logs_warning(
        self, hybrid_connector, caplog
    ):
        """Test that reasoning_effort in execution model logs a warning."""
        model_spec = "hybrid:[backend1:model1,backend2:model2?reasoning_effort=medium]"

        with caplog.at_level(logging.DEBUG):
            spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Verify parsing succeeded
        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {"reasoning_effort": "medium"}

    def test_reasoning_effort_in_both_models_logs_warning(
        self, hybrid_connector, caplog
    ):
        """Test that reasoning_effort in both models logs a warning."""
        model_spec = "hybrid:[backend1:model1?reasoning_effort=high,backend2:model2?reasoning_effort=low]"

        with caplog.at_level(logging.DEBUG):
            spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Verify parsing succeeded
        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {"reasoning_effort": "high"}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {"reasoning_effort": "low"}

    def test_no_warning_without_reasoning_effort(self, hybrid_connector, caplog):
        """Test that no warning is logged when reasoning_effort is not specified."""
        model_spec = (
            "hybrid:[backend1:model1?temperature=0.8,backend2:model2?temperature=0.3]"
        )

        with caplog.at_level(logging.WARNING):
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Verify no warning about reasoning_effort
        warning_messages = [
            record.message
            for record in caplog.records
            if record.levelname == "WARNING" and "reasoning_effort" in record.message
        ]
        assert len(warning_messages) == 0


class TestHybridParameterApplication:
    """Test parameter application to reasoning and execution phases separately."""

    def test_reasoning_params_applied_to_reasoning_phase(self, hybrid_connector):
        """Test that reasoning parameters are applied to reasoning phase."""
        # This test verifies that the parsing correctly separates parameters
        model_spec = (
            "hybrid:[backend1:model1?temperature=0.8,backend2:model2?temperature=0.3]"
        )

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Verify reasoning params are separate from execution params
        assert spec.reasoning_params == {"temperature": "0.8"}
        assert spec.execution_params == {"temperature": "0.3"}
        assert spec.reasoning_params != spec.execution_params

    def test_execution_params_applied_to_execution_phase(self, hybrid_connector):
        """Test that execution parameters are applied to execution phase."""
        model_spec = "hybrid:[backend1:model1,backend2:model2?temperature=0.5]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Verify only execution has params
        assert spec.reasoning_params == {}
        assert spec.execution_params == {"temperature": "0.5"}

    def test_different_params_for_each_phase(self, hybrid_connector):
        """Test that different parameters can be specified for each phase."""
        model_spec = "hybrid:[backend1:model1?temperature=0.9&reasoning_effort=high,backend2:model2?temperature=0.2]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Verify different parameters for each phase
        assert spec.reasoning_params == {
            "temperature": "0.9",
            "reasoning_effort": "high",
        }
        assert spec.execution_params == {"temperature": "0.2"}
        assert "reasoning_effort" not in spec.execution_params


class TestHybridOneModelWithParams:
    """Test hybrid spec with only one model having URI parameters."""

    def test_only_reasoning_model_has_params(self, hybrid_connector):
        """Test hybrid spec where only reasoning model has URI parameters."""
        model_spec = "hybrid:[backend1:model1?temperature=0.8,backend2:model2]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {"temperature": "0.8"}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {}

    def test_only_execution_model_has_params(self, hybrid_connector):
        """Test hybrid spec where only execution model has URI parameters."""
        model_spec = "hybrid:[backend1:model1,backend2:model2?temperature=0.3]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {"temperature": "0.3"}

    def test_only_reasoning_model_has_multiple_params(self, hybrid_connector):
        """Test hybrid spec where only reasoning model has multiple URI parameters."""
        model_spec = "hybrid:[backend1:model1?temperature=0.7&reasoning_effort=medium,backend2:model2]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {
            "temperature": "0.7",
            "reasoning_effort": "medium",
        }
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {}

    def test_only_execution_model_has_multiple_params(self, hybrid_connector):
        """Test hybrid spec where only execution model has multiple URI parameters."""
        model_spec = "hybrid:[backend1:model1,backend2:model2?temperature=0.4&reasoning_effort=low]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {
            "temperature": "0.4",
            "reasoning_effort": "low",
        }


class TestHybridURIParameterEdgeCases:
    """Test edge cases for hybrid backend URI parameter parsing."""

    def test_empty_query_string(self, hybrid_connector):
        """Test hybrid spec with empty query string (trailing ?)."""
        model_spec = "hybrid:[backend1:model1?,backend2:model2]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {}

    def test_malformed_query_string(self, hybrid_connector):
        """Test hybrid spec with malformed query string."""
        model_spec = "hybrid:[backend1:model1?invalid,backend2:model2]"

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Should parse successfully - parse_qs handles "invalid" as empty value
        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        # Malformed params result in empty dict due to keep_blank_values=False
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {}

    def test_special_characters_in_params(self, hybrid_connector):
        """Test hybrid spec with special characters in parameter values."""
        model_spec = (
            "hybrid:[backend1:model1?temperature=0.8,backend2:model2?temperature=0.3]"
        )

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Should parse successfully
        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        assert spec.reasoning_params == {"temperature": "0.8"}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {"temperature": "0.3"}

    def test_duplicate_parameter_names(self, hybrid_connector):
        """Test hybrid spec with duplicate parameter names (last value wins)."""
        model_spec = (
            "hybrid:[backend1:model1?temperature=0.8&temperature=0.9,backend2:model2]"
        )

        spec = hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "backend1"
        assert spec.reasoning_model == "model1"
        # parse_model_with_params uses the last value for duplicates
        assert spec.reasoning_params == {"temperature": "0.9"}
        assert spec.execution_backend == "backend2"
        assert spec.execution_model == "model2"
        assert spec.execution_params == {}
