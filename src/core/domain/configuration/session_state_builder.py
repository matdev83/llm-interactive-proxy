from __future__ import annotations

from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.configuration.project_config import ProjectConfiguration
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import SessionState


class SessionStateBuilder:
    """Builder for constructing SessionState objects.

    This builder makes it easier to create new SessionState instances by
    providing methods to set various properties.
    """

    def __init__(self, state: SessionState | None = None):
        """Initialize the builder, optionally with an existing state.

        Args:
            state: Optional existing state to modify
        """
        if state:
            self._backend_config = state.backend_config  # type: ignore
            self._reasoning_config = state.reasoning_config  # type: ignore
            self._loop_config = state.loop_config  # type: ignore
            self._project_config = ProjectConfiguration(
                project=state.project, project_dir=state.project_dir
            )
            self._interactive_just_enabled = state.interactive_just_enabled
            self._hello_requested = state.hello_requested
            self._is_cline_agent = state.is_cline_agent
        else:
            self._backend_config = BackendConfiguration()
            self._reasoning_config = ReasoningConfiguration()
            self._loop_config = LoopDetectionConfiguration()
            self._project_config = ProjectConfiguration()
            self._interactive_just_enabled = False
            self._hello_requested = False
            self._is_cline_agent = False

    def with_backend_config(
        self, backend_config: BackendConfiguration
    ) -> SessionStateBuilder:
        """Set the backend configuration.

        Args:
            backend_config: The backend configuration

        Returns:
            The builder instance for chaining
        """
        self._backend_config = backend_config
        return self

    def with_reasoning_config(
        self, reasoning_config: ReasoningConfiguration
    ) -> SessionStateBuilder:
        """Set the reasoning configuration.

        Args:
            reasoning_config: The reasoning configuration

        Returns:
            The builder instance for chaining
        """
        self._reasoning_config = reasoning_config
        return self

    def with_loop_config(
        self, loop_config: LoopDetectionConfiguration
    ) -> SessionStateBuilder:
        """Set the loop detection configuration.

        Args:
            loop_config: The loop detection configuration

        Returns:
            The builder instance for chaining
        """
        self._loop_config = loop_config
        return self

    def with_project_config(
        self, project_config: ProjectConfiguration
    ) -> SessionStateBuilder:
        """Set the project configuration.

        Args:
            project_config: The project configuration

        Returns:
            The builder instance for chaining
        """
        self._project_config = project_config
        return self

    def with_interactive_just_enabled(self, enabled: bool) -> SessionStateBuilder:
        """Set whether interactive mode was just enabled.

        Args:
            enabled: Whether interactive mode was just enabled

        Returns:
            The builder instance for chaining
        """
        self._interactive_just_enabled = enabled
        return self

    def with_hello_requested(self, requested: bool) -> SessionStateBuilder:
        """Set whether hello was requested.

        Args:
            requested: Whether hello was requested

        Returns:
            The builder instance for chaining
        """
        self._hello_requested = requested
        return self

    def with_is_cline_agent(self, is_cline: bool) -> SessionStateBuilder:
        """Set whether the agent is Cline.

        Args:
            is_cline: Whether the agent is Cline

        Returns:
            The builder instance for chaining
        """
        self._is_cline_agent = is_cline
        return self

    # Backend configuration shortcuts
    def with_backend_type(self, backend_type: str | None) -> SessionStateBuilder:
        """Set the backend type.

        Args:
            backend_type: The backend type

        Returns:
            The builder instance for chaining
        """
        self._backend_config = self._backend_config.with_backend(backend_type)
        return self

    def with_model(self, model: str) -> SessionStateBuilder:
        """Set the model.

        Args:
            model: The model

        Returns:
            The builder instance for chaining
        """
        self._backend_config = self._backend_config.with_model(model)
        return self

    def with_interactive_mode(self, enabled: bool) -> SessionStateBuilder:
        """Set interactive mode.

        Args:
            enabled: Whether interactive mode is enabled

        Returns:
            The builder instance for chaining
        """
        self._backend_config = self._backend_config.with_interactive_mode(enabled)
        if enabled and not self._backend_config.interactive_mode:
            self._interactive_just_enabled = True
        else:
            self._interactive_just_enabled = False
        return self

    # Reasoning configuration shortcuts
    def with_temperature(self, temperature: float) -> SessionStateBuilder:
        """Set the temperature.

        Args:
            temperature: The temperature

        Returns:
            The builder instance for chaining
        """
        self._reasoning_config = self._reasoning_config.with_temperature(temperature)
        return self

    def with_reasoning_effort(self, effort: str) -> SessionStateBuilder:
        """Set the reasoning effort.

        Args:
            effort: The reasoning effort

        Returns:
            The builder instance for chaining
        """
        self._reasoning_config = self._reasoning_config.with_reasoning_effort(effort)
        return self

    def with_thinking_budget(self, budget: int | None) -> SessionStateBuilder:
        """Set the thinking budget.

        Args:
            budget: The thinking budget

        Returns:
            The builder instance for chaining
        """
        self._reasoning_config = self._reasoning_config.with_thinking_budget(budget)
        return self

    # Project configuration shortcuts
    def with_project(self, project: str) -> SessionStateBuilder:
        """Set the project.

        Args:
            project: The project name

        Returns:
            The builder instance for chaining
        """
        self._project_config = self._project_config.with_project(project)
        return self

    def with_project_dir(self, project_dir: str) -> SessionStateBuilder:
        """Set the project directory.

        Args:
            project_dir: The project directory

        Returns:
            The builder instance for chaining
        """
        self._project_config = self._project_config.with_project_dir(project_dir)
        return self

    # Loop detection shortcuts
    def with_loop_detection_enabled(self, enabled: bool) -> SessionStateBuilder:
        """Set whether loop detection is enabled.

        Args:
            enabled: Whether loop detection is enabled

        Returns:
            The builder instance for chaining
        """
        self._loop_config = self._loop_config.with_loop_detection_enabled(enabled)
        return self

    def with_tool_loop_detection_enabled(self, enabled: bool) -> SessionStateBuilder:
        """Set whether tool loop detection is enabled.

        Args:
            enabled: Whether tool loop detection is enabled

        Returns:
            The builder instance for chaining
        """
        self._loop_config = self._loop_config.with_tool_loop_detection_enabled(enabled)
        return self

    def build(self) -> SessionState:
        """Build the SessionState.

        Returns:
            A new SessionState instance
        """
        return SessionState(
            backend_config=self._backend_config,
            reasoning_config=self._reasoning_config,
            loop_config=self._loop_config,
            project=self._project_config.project,
            project_dir=self._project_config.project_dir,
            interactive_just_enabled=self._interactive_just_enabled,
            hello_requested=self._hello_requested,
            is_cline_agent=self._is_cline_agent,
        )
