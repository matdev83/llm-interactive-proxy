"""Unit tests for parameter resolution service."""

import logging

import pytest
from src.core.services.parameter_resolution_service import (
    ParameterResolutionService,
    ParameterSource,
    ResolvedParameters,
)


class TestParameterSource:
    """Test cases for ParameterSource dataclass."""

    def test_parameter_source_creation(self):
        """Test creating a ParameterSource instance."""
        source = ParameterSource(value=0.5, source="uri")

        assert source.value == 0.5
        assert source.source == "uri"

    def test_parameter_source_repr(self):
        """Test ParameterSource string representation."""
        source = ParameterSource(value=0.7, source="header")
        repr_str = repr(source)

        assert "ParameterSource" in repr_str
        assert "0.7" in repr_str
        assert "header" in repr_str


class TestResolvedParameters:
    """Test cases for ResolvedParameters dataclass."""

    def test_resolved_parameters_creation_empty(self):
        """Test creating an empty ResolvedParameters instance."""
        params = ResolvedParameters()

        assert params.temperature is None
        assert params.reasoning_effort is None
        assert params.top_p is None
        assert params.top_k is None

    def test_resolved_parameters_creation_with_values(self):
        """Test creating ResolvedParameters with values."""
        temp_source = ParameterSource(value=0.5, source="uri")
        effort_source = ParameterSource(value="high", source="session")
        top_p_source = ParameterSource(value=0.9, source="config")
        top_k_source = ParameterSource(value=42, source="header")

        params = ResolvedParameters(
            temperature=temp_source,
            reasoning_effort=effort_source,
            top_p=top_p_source,
            top_k=top_k_source,
        )

        assert params.temperature == temp_source
        assert params.reasoning_effort == effort_source
        assert params.top_p == top_p_source
        assert params.top_k == top_k_source

    def test_to_dict_empty(self):
        """Test to_dict with no parameters."""
        params = ResolvedParameters()
        result = params.to_dict()

        assert result == {}

    def test_to_dict_with_temperature_only(self):
        """Test to_dict with only temperature."""
        params = ResolvedParameters(temperature=ParameterSource(0.5, "uri"))
        result = params.to_dict()

        assert result == {"temperature": 0.5}

    def test_to_dict_with_reasoning_effort_only(self):
        """Test to_dict with only reasoning_effort."""
        params = ResolvedParameters(reasoning_effort=ParameterSource("high", "session"))
        result = params.to_dict()

        assert result == {"reasoning_effort": "high"}

    def test_to_dict_with_both_parameters(self):
        """Test to_dict with both parameters."""
        params = ResolvedParameters(
            temperature=ParameterSource(0.7, "header"),
            reasoning_effort=ParameterSource("medium", "config"),
        )
        result = params.to_dict()

        assert result == {"temperature": 0.7, "reasoning_effort": "medium"}

    def test_to_dict_with_top_parameters(self):
        """Test to_dict with top_p and top_k parameters."""
        params = ResolvedParameters(
            top_p=ParameterSource(0.92, "uri"),
            top_k=ParameterSource(32, "session"),
        )
        result = params.to_dict()

        assert result == {"top_p": 0.92, "top_k": 32}

    def test_get_debug_info_empty(self):
        """Test get_debug_info with no parameters."""
        params = ResolvedParameters()
        debug_info = params.get_debug_info()

        assert debug_info == {}

    def test_get_debug_info_with_temperature(self):
        """Test get_debug_info with temperature."""
        params = ResolvedParameters(temperature=ParameterSource(0.5, "uri"))
        debug_info = params.get_debug_info()

        assert "temperature" in debug_info
        assert debug_info["temperature"].effective_value == 0.5
        assert debug_info["temperature"].source == "uri"

    def test_get_debug_info_with_reasoning_effort(self):
        """Test get_debug_info with reasoning_effort."""
        params = ResolvedParameters(reasoning_effort=ParameterSource("high", "session"))
        debug_info = params.get_debug_info()

        assert "reasoning_effort" in debug_info
        assert debug_info["reasoning_effort"].effective_value == "high"
        assert debug_info["reasoning_effort"].source == "session"

    def test_get_debug_info_with_both_parameters(self):
        """Test get_debug_info with both parameters."""
        params = ResolvedParameters(
            temperature=ParameterSource(0.8, "config"),
            reasoning_effort=ParameterSource("low", "header"),
        )
        debug_info = params.get_debug_info()

        assert len(debug_info) == 2
        assert debug_info["temperature"].effective_value == 0.8
        assert debug_info["temperature"].source == "config"
        assert debug_info["reasoning_effort"].effective_value == "low"
        assert debug_info["reasoning_effort"].source == "header"

    def test_get_debug_info_with_top_parameters(self):
        """Test get_debug_info includes top_p and top_k entries."""
        params = ResolvedParameters(
            top_p=ParameterSource(0.85, "uri"),
            top_k=ParameterSource(16, "session"),
        )
        debug_info = params.get_debug_info()

        assert "top_p" in debug_info
        assert debug_info["top_p"].effective_value == 0.85
        assert debug_info["top_p"].source == "uri"
        assert "top_k" in debug_info
        assert debug_info["top_k"].effective_value == 16
        assert debug_info["top_k"].source == "session"


class TestParameterResolutionService:
    """Test cases for ParameterResolutionService."""

    @pytest.fixture
    def service(self):
        """Create a service instance for testing."""
        return ParameterResolutionService()

    # ========================================================================
    # Precedence Order Tests
    # ========================================================================

    def test_precedence_config_only(self, service):
        """Test resolution with only config parameters."""
        result = service.resolve_parameters(config_params={"temperature": 0.8})

        assert result.temperature is not None
        assert result.temperature.value == 0.8
        assert result.temperature.source == "config"

    def test_precedence_header_overrides_config(self, service):
        """Test that header parameters override config parameters."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8}, header_params={"temperature": 0.6}
        )

        assert result.temperature is not None
        assert result.temperature.value == 0.6
        assert result.temperature.source == "header"

    def test_precedence_uri_overrides_header_and_config(self, service):
        """Test that URI parameters override header and config parameters."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            header_params={"temperature": 0.6},
            uri_params={"temperature": 0.4},
        )

        assert result.temperature is not None
        assert result.temperature.value == 0.4
        assert result.temperature.source == "uri"

    def test_precedence_session_overrides_all(self, service):
        """Test that session parameters override all other sources."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            header_params={"temperature": 0.6},
            uri_params={"temperature": 0.4},
            session_params={"temperature": 0.2},
        )

        assert result.temperature is not None
        assert result.temperature.value == 0.2
        assert result.temperature.source == "session"

    def test_precedence_uri_overrides_request_header_and_config(self, service):
        """URI parameters should override A-leg request/header/config parameters."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            header_params={"temperature": 0.6},
            uri_params={"temperature": 0.4},
            request_params={"temperature": 0.3},
        )

        assert result.temperature is not None
        assert result.temperature.value == 0.4
        assert result.temperature.source == "uri"

    def test_precedence_connector_forced_overrides_everything(self, service):
        """Connector-forced parameters should have the highest precedence."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            header_params={"temperature": 0.6},
            uri_params={"temperature": 0.4},
            request_params={"temperature": 0.3},
            session_params={"temperature": 0.2},
            connector_forced_params={"temperature": 0.1},
        )

        assert result.temperature is not None
        assert result.temperature.value == 0.1
        assert result.temperature.source == "connector_forced"

    def test_precedence_reasoning_effort_config_only(self, service):
        """Test reasoning_effort resolution with only config."""
        result = service.resolve_parameters(config_params={"reasoning_effort": "low"})

        assert result.reasoning_effort is not None
        assert result.reasoning_effort.value == "low"
        assert result.reasoning_effort.source == "config"

    def test_precedence_reasoning_effort_header_overrides_config(self, service):
        """Test that header reasoning_effort overrides config."""
        result = service.resolve_parameters(
            config_params={"reasoning_effort": "low"},
            header_params={"reasoning_effort": "medium"},
        )

        assert result.reasoning_effort is not None
        assert result.reasoning_effort.value == "medium"
        assert result.reasoning_effort.source == "header"

    def test_precedence_reasoning_effort_uri_overrides_header(self, service):
        """Test that URI reasoning_effort overrides header and config."""
        result = service.resolve_parameters(
            config_params={"reasoning_effort": "low"},
            header_params={"reasoning_effort": "medium"},
            uri_params={"reasoning_effort": "high"},
        )

        assert result.reasoning_effort is not None
        assert result.reasoning_effort.value == "high"
        assert result.reasoning_effort.source == "uri"

    def test_precedence_reasoning_effort_session_overrides_uri(self, service):
        """Test that session reasoning_effort overrides URI and other sources."""
        result = service.resolve_parameters(
            config_params={"reasoning_effort": "low"},
            header_params={"reasoning_effort": "medium"},
            uri_params={"reasoning_effort": "high"},
            session_params={"reasoning_effort": "low"},
        )

        assert result.reasoning_effort is not None
        assert result.reasoning_effort.value == "low"
        assert result.reasoning_effort.source == "session"

    def test_precedence_mixed_parameters_different_sources(self, service):
        """Test precedence with different parameters from different sources."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8, "reasoning_effort": "low"},
            uri_params={"temperature": 0.5},
            session_params={"reasoning_effort": "high"},
        )

        # Temperature from URI (overrides config)
        assert result.temperature is not None
        assert result.temperature.value == 0.5
        assert result.temperature.source == "uri"

        # Reasoning effort from session (overrides config)
        assert result.reasoning_effort is not None
        assert result.reasoning_effort.value == "high"
        assert result.reasoning_effort.source == "session"

    def test_precedence_top_p_all_sources(self, service):
        """Test precedence handling for top_p across all sources."""
        result = service.resolve_parameters(
            config_params={"top_p": 0.2},
            header_params={"top_p": 0.4},
            uri_params={"top_p": 0.6},
            session_params={"top_p": 0.8},
        )

        assert result.top_p is not None
        assert result.top_p.value == 0.8
        assert result.top_p.source == "session"

    def test_precedence_top_k_uri_overrides(self, service):
        """Test precedence for top_k where URI overrides config/header."""
        result = service.resolve_parameters(
            config_params={"top_k": 16},
            header_params={"top_k": 24},
            uri_params={"top_k": 32},
        )

        assert result.top_k is not None
        assert result.top_k.value == 32
        assert result.top_k.source == "uri"

    # ========================================================================
    # Source Tracking Tests
    # ========================================================================

    def test_source_tracking_single_source(self, service):
        """Test source tracking with a single source."""
        result = service.resolve_parameters(uri_params={"temperature": 0.5})

        assert result.temperature is not None
        assert result.temperature.source == "uri"

    def test_source_tracking_multiple_sources_temperature(self, service):
        """Test source tracking for temperature from multiple sources."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            header_params={"temperature": 0.6},
            uri_params={"temperature": 0.4},
        )

        # Should track that URI is the effective source
        assert result.temperature.source == "uri"

    def test_source_tracking_multiple_sources_reasoning_effort(self, service):
        """Test source tracking for reasoning_effort from multiple sources."""
        result = service.resolve_parameters(
            config_params={"reasoning_effort": "low"},
            session_params={"reasoning_effort": "high"},
        )

        # Should track that session is the effective source
        assert result.reasoning_effort.source == "session"

    def test_source_tracking_independent_parameters(self, service):
        """Test that source tracking is independent for each parameter."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            uri_params={"reasoning_effort": "medium"},
        )

        assert result.temperature.source == "config"
        assert result.reasoning_effort.source == "uri"

    def test_source_tracking_top_parameters(self, service):
        """Test source tracking for top_p and top_k parameters."""
        result = service.resolve_parameters(
            config_params={"top_p": 0.2, "top_k": 16},
            session_params={"top_k": 64},
            uri_params={"top_p": 0.9},
        )

        assert result.top_p is not None
        assert result.top_p.source == "uri"
        assert result.top_p.value == 0.9
        assert result.top_k is not None
        assert result.top_k.source == "session"
        assert result.top_k.value == 64

    # ========================================================================
    # Debug Output Tests
    # ========================================================================

    def test_debug_output_format_single_parameter(self, service, caplog):
        """Test debug output format with a single parameter."""
        with caplog.at_level(logging.DEBUG):
            _result = service.resolve_parameters(
                uri_params={"temperature": 0.5}, backend="openai:gpt-4"
            )

        assert "Parameter resolution for openai:gpt-4" in caplog.text
        assert "temperature: 0.5" in caplog.text
        assert "source: uri" in caplog.text

    def test_debug_output_format_multiple_parameters(self, service, caplog):
        """Test debug output format with multiple parameters."""
        with caplog.at_level(logging.DEBUG):
            _result = service.resolve_parameters(
                uri_params={"temperature": 0.5, "reasoning_effort": "high"},
                backend="anthropic:claude",
            )

        assert "Parameter resolution for anthropic:claude" in caplog.text
        assert "temperature: 0.5" in caplog.text
        assert "reasoning_effort: high" in caplog.text

    def test_debug_output_includes_top_parameters(self, service, caplog):
        """Test debug logging includes top_p and top_k values."""
        with caplog.at_level(logging.DEBUG):
            _result = service.resolve_parameters(
                uri_params={"top_p": 0.9},
                header_params={"top_k": 24},
                backend="test:debug",
            )

        assert "Parameter resolution for test:debug" in caplog.text
        assert "top_p: 0.9" in caplog.text
        assert "top_k: 24" in caplog.text

    def test_debug_output_shows_overridden_sources(self, service, caplog):
        """Test that debug output shows overridden sources."""
        with caplog.at_level(logging.DEBUG):
            _result = service.resolve_parameters(
                config_params={"temperature": 0.8},
                header_params={"temperature": 0.6},
                uri_params={"temperature": 0.4},
                backend="test:model",
            )

        assert "temperature: 0.4" in caplog.text
        assert "source: uri" in caplog.text
        assert "overrode:" in caplog.text
        assert "config=0.8" in caplog.text
        assert "header=0.6" in caplog.text

    def test_debug_output_no_overrides(self, service, caplog):
        """Test debug output when there are no overrides."""
        with caplog.at_level(logging.DEBUG):
            _result = service.resolve_parameters(
                uri_params={"temperature": 0.5}, backend="test:model"
            )

        assert "temperature: 0.5" in caplog.text
        assert "source: uri" in caplog.text
        # Should not contain "overrode:" when there are no overrides
        log_lines = [line for line in caplog.text.split("\n") if "temperature" in line]
        assert any(
            "source: uri" in line and "overrode:" not in line for line in log_lines
        )

    def test_debug_output_empty_parameters(self, service, caplog):
        """Test that no debug output is generated for empty parameters."""
        with caplog.at_level(logging.DEBUG):
            _result = service.resolve_parameters(backend="test:model")

        # Should not log anything when no parameters are resolved
        assert "Parameter resolution" not in caplog.text

    def test_debug_info_structure(self, service):
        """Test the structure of debug info returned by get_debug_info."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            uri_params={"temperature": 0.5, "reasoning_effort": "high"},
        )

        debug_info = result.get_debug_info()

        assert "temperature" in debug_info
        assert "reasoning_effort" in debug_info
        assert debug_info["temperature"].effective_value == 0.5
        assert debug_info["temperature"].source == "uri"
        assert debug_info["reasoning_effort"].effective_value == "high"
        assert debug_info["reasoning_effort"].source == "uri"

    # ========================================================================
    # Missing Sources Tests
    # ========================================================================

    def test_missing_all_sources(self, service):
        """Test resolution when all sources are missing."""
        result = service.resolve_parameters()

        assert result.temperature is None
        assert result.reasoning_effort is None
        assert result.top_p is None
        assert result.top_k is None

    def test_missing_session_params(self, service):
        """Test resolution when session params are missing."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            header_params={"temperature": 0.6},
            uri_params={"temperature": 0.4},
        )

        # Should still resolve correctly without session params
        assert result.temperature.value == 0.4
        assert result.temperature.source == "uri"

    def test_missing_uri_params(self, service):
        """Test resolution when URI params are missing."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            header_params={"temperature": 0.6},
            session_params={"temperature": 0.2},
        )

        # Should still resolve correctly without URI params
        assert result.temperature.value == 0.2
        assert result.temperature.source == "session"

    def test_missing_header_params(self, service):
        """Test resolution when header params are missing."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            uri_params={"temperature": 0.4},
            session_params={"temperature": 0.2},
        )

        # Should still resolve correctly without header params
        assert result.temperature.value == 0.2
        assert result.temperature.source == "session"

    def test_missing_config_params(self, service):
        """Test resolution when config params are missing."""
        result = service.resolve_parameters(
            header_params={"temperature": 0.6},
            uri_params={"temperature": 0.4},
            session_params={"temperature": 0.2},
        )

        # Should still resolve correctly without config params
        assert result.temperature.value == 0.2
        assert result.temperature.source == "session"

    def test_missing_multiple_sources(self, service):
        """Test resolution when multiple sources are missing."""
        result = service.resolve_parameters(uri_params={"temperature": 0.5})

        # Should resolve with only URI params
        assert result.temperature.value == 0.5
        assert result.temperature.source == "uri"
        assert result.reasoning_effort is None

    def test_partial_parameters_across_sources(self, service):
        """Test resolution with partial parameters from different sources."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            uri_params={"reasoning_effort": "high"},
        )

        assert result.temperature.value == 0.8
        assert result.temperature.source == "config"
        assert result.reasoning_effort.value == "high"
        assert result.reasoning_effort.source == "uri"

    def test_none_values_treated_as_missing(self, service):
        """Test that None values in parameter dicts are treated as missing."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            uri_params={"temperature": None},
        )

        # None in URI params should not override config
        assert result.temperature.value == 0.8
        assert result.temperature.source == "config"

    # ========================================================================
    # Edge Cases and Special Scenarios
    # ========================================================================

    def test_empty_dict_sources(self, service):
        """Test resolution with empty dict sources."""
        result = service.resolve_parameters(
            config_params={}, header_params={}, uri_params={}, session_params={}
        )

        assert result.temperature is None
        assert result.reasoning_effort is None

    def test_backend_parameter_in_logging(self, service, caplog):
        """Test that backend parameter is used in logging."""
        with caplog.at_level(logging.DEBUG):
            _result = service.resolve_parameters(
                uri_params={"temperature": 0.5}, backend="custom:backend:model"
            )

        assert "custom:backend:model" in caplog.text

    def test_empty_backend_string(self, service, caplog):
        """Test resolution with empty backend string."""
        with caplog.at_level(logging.DEBUG):
            result = service.resolve_parameters(
                uri_params={"temperature": 0.5}, backend=""
            )

        # Should still work, just with empty backend in logs
        assert result.temperature.value == 0.5

    def test_parameter_value_types_preserved(self, service):
        """Test that parameter value types are preserved through resolution."""
        result = service.resolve_parameters(
            uri_params={"temperature": 0.5, "reasoning_effort": "high"}
        )

        assert isinstance(result.temperature.value, float)
        assert isinstance(result.reasoning_effort.value, str)

    def test_resolution_with_all_sources_different_params(self, service):
        """Test resolution when each source provides different parameters."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.8},
            header_params={"reasoning_effort": "low"},
            uri_params={},
            session_params={},
        )

        assert result.temperature.value == 0.8
        assert result.temperature.source == "config"
        assert result.reasoning_effort.value == "low"
        assert result.reasoning_effort.source == "header"

    def test_override_tracking_all_sources(self, service, caplog):
        """Test that all overridden sources are tracked in debug output."""
        with caplog.at_level(logging.DEBUG):
            _result = service.resolve_parameters(
                config_params={"temperature": 0.1},
                header_params={"temperature": 0.3},
                uri_params={"temperature": 0.5},
                session_params={"temperature": 0.7},
                backend="test:model",
            )

        # Session should be effective and should show all overridden sources
        assert "temperature: 0.7" in caplog.text
        assert "source: session" in caplog.text
        assert "config=0.1" in caplog.text
        assert "header=0.3" in caplog.text
        assert "uri=0.5" in caplog.text

    def test_to_dict_excludes_none_values(self, service):
        """Test that to_dict excludes None values."""
        result = service.resolve_parameters(uri_params={"temperature": 0.5})

        result_dict = result.to_dict()

        assert "temperature" in result_dict
        assert "reasoning_effort" not in result_dict

    def test_supported_parameters_constant(self, service):
        """Test that SUPPORTED_PARAMETERS constant is defined correctly."""
        assert hasattr(service, "SUPPORTED_PARAMETERS")
        assert "temperature" in service.SUPPORTED_PARAMETERS
        assert "reasoning_effort" in service.SUPPORTED_PARAMETERS
        assert "top_p" in service.SUPPORTED_PARAMETERS
        assert "top_k" in service.SUPPORTED_PARAMETERS
        assert len(service.SUPPORTED_PARAMETERS) == 4

    # ========================================================================
    # Integration-like Tests
    # ========================================================================

    def test_realistic_scenario_uri_overrides(self, service):
        """Test realistic scenario where URI params override config."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.7, "reasoning_effort": "medium"},
            uri_params={"temperature": 0.9},
            backend="openai:gpt-4",
        )

        assert result.temperature.value == 0.9
        assert result.temperature.source == "uri"
        assert result.reasoning_effort.value == "medium"
        assert result.reasoning_effort.source == "config"

    def test_realistic_scenario_session_commands(self, service):
        """Test realistic scenario where session commands override URI."""
        result = service.resolve_parameters(
            config_params={"temperature": 0.7},
            header_params={"temperature": 0.8},
            uri_params={"temperature": 0.9},
            session_params={"temperature": 0.5},
            backend="anthropic:claude-3",
        )

        assert result.temperature.value == 0.5
        assert result.temperature.source == "session"

    def test_realistic_scenario_no_overrides(self, service):
        """Test realistic scenario where each source provides unique parameters."""
        result = service.resolve_parameters(
            config_params={"reasoning_effort": "low"},
            uri_params={"temperature": 0.6},
            backend="gemini:pro",
        )

        assert result.temperature.value == 0.6
        assert result.temperature.source == "uri"
        assert result.reasoning_effort.value == "low"
        assert result.reasoning_effort.source == "config"
