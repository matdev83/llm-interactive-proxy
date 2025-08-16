"""
Tests for configuration interfaces and implementations.
"""

import pytest
from pydantic import ValidationError
from src.core.domain.configuration import (
    BackendConfiguration,
    LoopDetectionConfiguration,
    ReasoningConfiguration,
)
from src.core.interfaces.configuration import (
    IBackendConfig,
    ILoopDetectionConfig,
    IReasoningConfig,
)


class TestBackendConfigInterface:
    """Test BackendConfiguration implementation of IBackendConfig interface."""

    def test_backend_config_implements_interface(self):
        """Test that BackendConfiguration properly implements IBackendConfig."""
        config = BackendConfiguration(
            backend_type="openai",
            model="gpt-4",
            api_url="https://api.openai.com/v1",
            interactive_mode=True,
        )

        # Verify it implements the interface
        assert isinstance(config, IBackendConfig)

        # Test interface methods
        assert config.backend_type == "openai"
        assert config.model == "gpt-4"
        assert config.api_url == "https://api.openai.com/v1"
        assert config.interactive_mode is True
        assert isinstance(config.failover_routes, dict)

    def test_backend_config_with_methods(self):
        """Test BackendConfiguration with_* methods return correct interface type."""
        config = BackendConfiguration(backend_type="openai", model="gpt-4")

        # Test with_backend method
        new_config = config.with_backend("anthropic")
        assert isinstance(new_config, IBackendConfig)
        assert new_config.backend_type == "anthropic"
        assert new_config.model == "gpt-4"  # Preserved

        # Test with_model method
        new_config = config.with_model("gpt-3.5-turbo")
        assert isinstance(new_config, IBackendConfig)
        assert new_config.backend_type == "openai"  # Preserved
        assert new_config.model == "gpt-3.5-turbo"

        # Test with_api_url method
        new_config = config.with_api_url("https://custom.api.com")
        assert isinstance(new_config, IBackendConfig)
        assert new_config.api_url == "https://custom.api.com"

        # Test with_interactive_mode method
        new_config = config.with_interactive_mode(False)
        assert isinstance(new_config, IBackendConfig)
        assert new_config.interactive_mode is False

    def test_backend_config_chaining(self):
        """Test that BackendConfiguration methods can be chained."""
        config = BackendConfiguration()

        final_config = (
            config.with_backend("anthropic")
            .with_model("claude-3")
            .with_api_url("https://api.anthropic.com")
            .with_interactive_mode(False)
        )

        assert isinstance(final_config, IBackendConfig)
        assert final_config.backend_type == "anthropic"
        assert final_config.model == "claude-3"
        assert final_config.api_url == "https://api.anthropic.com"
        assert final_config.interactive_mode is False


class TestReasoningConfigInterface:
    """Test ReasoningConfiguration implementation of IReasoningConfig interface."""

    def test_reasoning_config_implements_interface(self):
        """Test that ReasoningConfiguration properly implements IReasoningConfig."""
        config = ReasoningConfiguration(
            reasoning_effort="high",
            thinking_budget=1000,
            temperature=0.7,
        )

        # Verify it implements the interface
        assert isinstance(config, IReasoningConfig)

        # Test interface methods
        assert config.reasoning_effort == "high"
        assert config.thinking_budget == 1000
        assert config.temperature == 0.7

    def test_reasoning_config_with_methods(self):
        """Test ReasoningConfiguration with_* methods return correct interface type."""
        config = ReasoningConfiguration(reasoning_effort="medium", temperature=0.5)

        # Test with_reasoning_effort method
        new_config = config.with_reasoning_effort("high")
        assert isinstance(new_config, IReasoningConfig)
        assert new_config.reasoning_effort == "high"
        assert new_config.temperature == 0.5  # Preserved

        # Test with_thinking_budget method
        new_config = config.with_thinking_budget(2000)
        assert isinstance(new_config, IReasoningConfig)
        assert new_config.thinking_budget == 2000

        # Test with_temperature method
        new_config = config.with_temperature(0.8)
        assert isinstance(new_config, IReasoningConfig)
        assert new_config.temperature == 0.8

    def test_reasoning_config_chaining(self):
        """Test that ReasoningConfiguration methods can be chained."""
        config = ReasoningConfiguration()

        final_config = (
            config.with_reasoning_effort("high")
            .with_thinking_budget(1500)
            .with_temperature(0.9)
        )

        assert isinstance(final_config, IReasoningConfig)
        assert final_config.reasoning_effort == "high"
        assert final_config.thinking_budget == 1500
        assert final_config.temperature == 0.9


class TestLoopDetectionConfigInterface:
    """Test LoopDetectionConfiguration implementation of ILoopDetectionConfig interface."""

    def test_loop_detection_config_implements_interface(self):
        """Test that LoopDetectionConfiguration properly implements ILoopDetectionConfig."""
        config = LoopDetectionConfiguration(
            loop_detection_enabled=True,
            tool_loop_detection_enabled=False,
            min_pattern_length=50,
            max_pattern_length=1000,
        )

        # Verify it implements the interface
        assert isinstance(config, ILoopDetectionConfig)

        # Test interface methods
        assert config.loop_detection_enabled is True
        assert config.tool_loop_detection_enabled is False
        assert config.min_pattern_length == 50
        assert config.max_pattern_length == 1000

    def test_loop_detection_config_with_methods(self):
        """Test LoopDetectionConfiguration with_* methods return correct interface type."""
        config = LoopDetectionConfiguration(
            loop_detection_enabled=True, tool_loop_detection_enabled=True
        )

        # Test with_loop_detection_enabled method
        new_config = config.with_loop_detection_enabled(False)
        assert isinstance(new_config, ILoopDetectionConfig)
        assert new_config.loop_detection_enabled is False
        assert new_config.tool_loop_detection_enabled is True  # Preserved

        # Test with_tool_loop_detection_enabled method
        new_config = config.with_tool_loop_detection_enabled(False)
        assert isinstance(new_config, ILoopDetectionConfig)
        assert new_config.tool_loop_detection_enabled is False

        # Test with_pattern_length_range method
        new_config = config.with_pattern_length_range(25, 500)
        assert isinstance(new_config, ILoopDetectionConfig)
        assert new_config.min_pattern_length == 25
        assert new_config.max_pattern_length == 500

    def test_loop_detection_config_chaining(self):
        """Test that LoopDetectionConfiguration methods can be chained."""
        config = LoopDetectionConfiguration()

        final_config = (
            config.with_loop_detection_enabled(False)
            .with_tool_loop_detection_enabled(True)
            .with_pattern_length_range(75, 750)
        )

        assert isinstance(final_config, ILoopDetectionConfig)
        assert final_config.loop_detection_enabled is False
        assert final_config.tool_loop_detection_enabled is True
        assert final_config.min_pattern_length == 75
        assert final_config.max_pattern_length == 750


class TestConfigurationDefaults:
    """Test that configuration objects have sensible defaults."""

    def test_backend_config_defaults(self):
        """Test BackendConfiguration default values."""
        config = BackendConfiguration()

        assert config.backend_type is None
        assert config.model is None
        assert config.api_url is None
        assert config.interactive_mode is True
        assert config.failover_routes == {}

    def test_reasoning_config_defaults(self):
        """Test ReasoningConfiguration default values."""
        config = ReasoningConfiguration()

        assert config.reasoning_effort is None
        assert config.thinking_budget is None
        assert config.temperature is None

    def test_loop_detection_config_defaults(self):
        """Test LoopDetectionConfiguration default values."""
        config = LoopDetectionConfiguration()

        assert config.loop_detection_enabled is True
        assert config.tool_loop_detection_enabled is True
        assert config.min_pattern_length == 100
        assert config.max_pattern_length == 8000


class TestConfigurationImmutability:
    """Test that configuration objects are properly immutable."""

    def test_backend_config_immutability(self):
        """Test that BackendConfiguration is immutable."""
        config = BackendConfiguration(backend_type="openai", model="gpt-4")

        # Direct assignment should fail
        with pytest.raises(ValidationError):  # ValidationError from Pydantic
            config.backend_type = "anthropic"

        with pytest.raises(ValidationError):
            config.model = "claude-3"

    def test_reasoning_config_immutability(self):
        """Test that ReasoningConfiguration is immutable."""
        config = ReasoningConfiguration(temperature=0.7)

        # Direct assignment should fail
        with pytest.raises(ValidationError):
            config.temperature = 0.8

        with pytest.raises(ValidationError):
            config.reasoning_effort = "high"

    def test_loop_detection_config_immutability(self):
        """Test that LoopDetectionConfiguration is immutable."""
        config = LoopDetectionConfiguration(loop_detection_enabled=True)

        # Direct assignment should fail
        with pytest.raises(ValidationError):
            config.loop_detection_enabled = False

        with pytest.raises(ValidationError):
            config.min_pattern_length = 50