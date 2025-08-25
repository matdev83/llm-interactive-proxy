"""
Tests for SessionStateBuilder class.

This module tests the session state builder functionality for constructing
SessionState objects with various configurations.
"""

from unittest.mock import Mock

from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.configuration.project_config import ProjectConfiguration
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionState


class TestSessionStateBuilder:
    """Tests for SessionStateBuilder class."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        builder = SessionStateBuilder()

        # Check that all configurations are initialized with defaults
        assert isinstance(builder._backend_config, BackendConfiguration)
        assert isinstance(builder._reasoning_config, ReasoningConfiguration)
        assert isinstance(builder._loop_config, LoopDetectionConfiguration)
        assert isinstance(builder._project_config, ProjectConfiguration)

        # Check default flags
        assert builder._interactive_just_enabled is False
        assert builder._hello_requested is False
        assert builder._is_cline_agent is False

    def test_initialization_with_existing_state(self) -> None:
        """Test initialization with existing session state."""
        # Create a mock session state with proper configuration objects
        mock_state = Mock()
        mock_state.backend_config = BackendConfiguration(
            backend_type="openai",
            model="gpt-4",
        )
        mock_state.reasoning_config = ReasoningConfiguration(
            reasoning_effort="high",
            temperature=0.5,
        )
        mock_state.loop_config = LoopDetectionConfiguration(
            loop_detection_enabled=False,
        )
        mock_state.project = "test-project"
        mock_state.project_dir = "/test/path"
        mock_state.interactive_just_enabled = True
        mock_state.hello_requested = True
        mock_state.is_cline_agent = True

        builder = SessionStateBuilder(mock_state)

        # Check that configurations were copied from existing state
        assert builder._backend_config.backend_type == "openai"
        assert builder._backend_config.model == "gpt-4"
        assert builder._reasoning_config.reasoning_effort == "high"
        assert builder._reasoning_config.temperature == 0.5
        assert builder._loop_config.loop_detection_enabled is False
        assert builder._project_config.project == "test-project"
        assert builder._project_config.project_dir == "/test/path"
        assert builder._interactive_just_enabled is True
        assert builder._hello_requested is True
        assert builder._is_cline_agent is True

    def test_with_backend_config_method(self) -> None:
        """Test with_backend_config method."""
        builder = SessionStateBuilder()
        new_config = BackendConfiguration(backend_type_value="anthropic")

        result = builder.with_backend_config(new_config)

        assert result is builder  # Should return self for chaining
        assert builder._backend_config is new_config

    def test_with_reasoning_config_method(self) -> None:
        """Test with_reasoning_config method."""
        builder = SessionStateBuilder()
        new_config = ReasoningConfiguration(reasoning_effort="low")

        result = builder.with_reasoning_config(new_config)

        assert result is builder
        assert builder._reasoning_config is new_config

    def test_with_loop_config_method(self) -> None:
        """Test with_loop_config method."""
        builder = SessionStateBuilder()
        new_config = LoopDetectionConfiguration(loop_detection_enabled=False)

        result = builder.with_loop_config(new_config)

        assert result is builder
        assert builder._loop_config is new_config

    def test_with_project_config_method(self) -> None:
        """Test with_project_config method."""
        builder = SessionStateBuilder()
        new_config = ProjectConfiguration(project="new-project")

        result = builder.with_project_config(new_config)

        assert result is builder
        assert builder._project_config is new_config

    def test_flag_setting_methods(self) -> None:
        """Test methods for setting boolean flags."""
        builder = SessionStateBuilder()

        # Test interactive_just_enabled
        result = builder.with_interactive_just_enabled(True)
        assert result is builder
        assert builder._interactive_just_enabled is True

        # Test hello_requested
        result = builder.with_hello_requested(True)
        assert result is builder
        assert builder._hello_requested is True

        # Test is_cline_agent
        result = builder.with_is_cline_agent(True)
        assert result is builder
        assert builder._is_cline_agent is True

    def test_backend_shortcut_methods(self) -> None:
        """Test backend configuration shortcut methods."""
        builder = SessionStateBuilder()

        # Test with_backend_type
        result = builder.with_backend_type("openai")
        assert result is builder
        assert builder._backend_config.backend_type == "openai"

        # Test with_model
        result = builder.with_model("gpt-4")
        assert result is builder
        assert builder._backend_config.model == "gpt-4"

        # Test with_interactive_mode
        result = builder.with_interactive_mode(False)
        assert result is builder
        assert builder._interactive_just_enabled is False
        assert builder._backend_config.interactive_mode is False

    def test_reasoning_shortcut_methods(self) -> None:
        """Test reasoning configuration shortcut methods."""
        builder = SessionStateBuilder()

        # Test with_temperature
        result = builder.with_temperature(0.7)
        assert result is builder
        assert builder._reasoning_config.temperature == 0.7

        # Test with_reasoning_effort
        result = builder.with_reasoning_effort("high")
        assert result is builder
        assert builder._reasoning_config.reasoning_effort == "high"

        # Test with_thinking_budget
        result = builder.with_thinking_budget(1024)
        assert result is builder
        assert builder._reasoning_config.thinking_budget == 1024

    def test_project_shortcut_methods(self) -> None:
        """Test project configuration shortcut methods."""
        builder = SessionStateBuilder()

        # Test with_project
        result = builder.with_project("test-app")
        assert result is builder
        assert builder._project_config.project == "test-app"

        # Test with_project_dir
        result = builder.with_project_dir("/path/to/app")
        assert result is builder
        assert builder._project_config.project_dir == "/path/to/app"

    def test_loop_shortcut_methods(self) -> None:
        """Test loop detection shortcut methods."""
        builder = SessionStateBuilder()

        # Test with_loop_detection_enabled
        result = builder.with_loop_detection_enabled(False)
        assert result is builder
        assert builder._loop_config.loop_detection_enabled is False

        # Test with_tool_loop_detection_enabled
        result = builder.with_tool_loop_detection_enabled(False)
        assert result is builder
        assert builder._loop_config.tool_loop_detection_enabled is False

    def test_build_method(self) -> None:
        """Test build method creates SessionState correctly."""
        builder = SessionStateBuilder()

        # Configure the builder
        builder.with_backend_type("anthropic")
        builder.with_model("claude-3")
        builder.with_temperature(0.5)
        builder.with_project("my-app")
        builder.with_interactive_just_enabled(True)
        builder.with_hello_requested(True)
        builder.with_is_cline_agent(True)

        # Build the session state
        session_state = builder.build()

        assert isinstance(session_state, SessionState)
        assert session_state.backend_config.backend_type == "anthropic"
        assert session_state.backend_config.model == "claude-3"
        assert session_state.reasoning_config.temperature == 0.5
        assert session_state.project == "my-app"
        assert session_state.interactive_just_enabled is True
        assert session_state.hello_requested is True
        assert session_state.is_cline_agent is True

    def test_method_chaining(self) -> None:
        """Test that methods can be chained together."""
        builder = SessionStateBuilder()

        # Chain multiple method calls
        result = (
            builder
            .with_backend_type("openai")
            .with_model("gpt-4")
            .with_temperature(0.3)
            .with_reasoning_effort("high")
            .with_project("chained-app")
            .with_loop_detection_enabled(False)
            .with_interactive_just_enabled(True)
            .with_hello_requested(True)
            .with_is_cline_agent(False)
        )

        # Verify the builder is returned for chaining
        assert result is builder

        # Build and verify the final state
        session_state = builder.build()

        assert session_state.backend_config.backend_type == "openai"
        assert session_state.backend_config.model == "gpt-4"
        assert session_state.reasoning_config.temperature == 0.3
        assert session_state.reasoning_config.reasoning_effort == "high"
        assert session_state.project == "chained-app"
        assert session_state.loop_config.loop_detection_enabled is False
        assert session_state.interactive_just_enabled is True
        assert session_state.hello_requested is True
        assert session_state.is_cline_agent is False

    def test_complex_configuration_setup(self) -> None:
        """Test complex configuration setup with all components."""
        builder = SessionStateBuilder()

        # Set up comprehensive configuration
        builder.with_backend_type("anthropic")
        builder.with_model("claude-3-opus")

        builder.with_temperature(0.1)
        builder.with_reasoning_effort("high")
        builder.with_thinking_budget(4096)

        builder.with_loop_detection_enabled(True)
        builder.with_tool_loop_detection_enabled(True)
        builder.with_pattern_length_range(200, 10000)

        builder.with_project("complex-app")
        builder.with_project_dir("/workspace/complex-app")

        builder.with_interactive_mode(True)
        builder.with_hello_requested(True)

        # Build and verify
        session_state = builder.build()

        # Verify backend config
        assert session_state.backend_config.backend_type == "anthropic"
        assert session_state.backend_config.model == "claude-3-opus"

        # Verify reasoning config
        assert session_state.reasoning_config.temperature == 0.1
        assert session_state.reasoning_config.reasoning_effort == "high"
        assert session_state.reasoning_config.thinking_budget == 4096

        # Verify loop config
        assert session_state.loop_config.loop_detection_enabled is True
        assert session_state.loop_config.tool_loop_detection_enabled is True
        assert session_state.loop_config.min_pattern_length == 200
        assert session_state.loop_config.max_pattern_length == 10000

        # Verify project config
        assert session_state.project == "complex-app"
        assert session_state.project_dir == "/workspace/complex-app"

        # Verify flags
        assert session_state.interactive_just_enabled is False  # Already True by default, so not "just enabled"
        assert session_state.hello_requested is True

    def test_immutability_of_configurations(self) -> None:
        """Test that configuration objects remain immutable."""
        builder = SessionStateBuilder()

        # Get initial configurations
        initial_backend = builder._backend_config
        initial_reasoning = builder._reasoning_config
        initial_loop = builder._loop_config
        initial_project = builder._project_config

        # Modify configurations through builder
        builder.with_backend_type("openai")
        builder.with_temperature(0.8)
        builder.with_loop_detection_enabled(False)
        builder.with_project("test")

        # Verify that original configurations were not modified
        assert initial_backend.backend_type is None
        assert initial_reasoning.temperature is None
        assert initial_loop.loop_detection_enabled is True
        assert initial_project.project is None

        # Verify that builder has new configurations
        assert builder._backend_config.backend_type == "openai"
        assert builder._reasoning_config.temperature == 0.8
        assert builder._loop_config.loop_detection_enabled is False
        assert builder._project_config.project == "test"

    def test_interactive_mode_state_changes(self) -> None:
        """Test that interactive mode changes affect the just_enabled flag."""
        builder = SessionStateBuilder()

        # Start with default interactive mode (True)
        assert builder._backend_config.interactive_mode is True
        assert builder._interactive_just_enabled is False

        # Change to False
        builder.with_interactive_mode(False)
        assert builder._backend_config.interactive_mode is False
        assert builder._interactive_just_enabled is False

        # Change back to True
        builder.with_interactive_mode(True)
        assert builder._backend_config.interactive_mode is True
        assert builder._interactive_just_enabled is False
