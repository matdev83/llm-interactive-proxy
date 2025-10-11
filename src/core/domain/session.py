from __future__ import annotations

# type: ignore[unreachable]
import contextlib
import logging
from datetime import datetime, timezone
from typing import Any, cast

logger = logging.getLogger(__name__)

from pydantic import ConfigDict, Field

from src.core.domain.base import ValueObject
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.configuration.planning_phase_config import (
    PlanningPhaseConfiguration,
)
from src.core.domain.configuration.reasoning_aliases_config import ReasoningMode
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.interfaces.configuration_interface import (
    IBackendConfig,
    ILoopDetectionConfig,
    IPlanningPhaseConfig,
    IReasoningConfig,
)
from src.core.interfaces.domain_entities_interface import (
    ISession,
    ISessionState,
    ISessionStateMutator,
)


class SessionInteraction(ValueObject):
    """Represents one user prompt and the resulting response."""

    prompt: str
    handler: str  # "proxy" or "backend"
    backend: str | None = None
    model: str | None = None
    project: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    response: str | None = None
    usage: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionState(ValueObject):
    """Immutable state of a session."""

    model_config = ConfigDict(
        # Other config options can be added here as needed
        arbitrary_types_allowed=True,
        frozen=True,
    )

    backend_config: BackendConfiguration = Field(default_factory=BackendConfiguration)
    reasoning_config: ReasoningConfiguration = Field(
        default_factory=ReasoningConfiguration
    )
    loop_config: LoopDetectionConfiguration = Field(
        default_factory=LoopDetectionConfiguration
    )
    planning_phase_config: PlanningPhaseConfiguration = Field(
        default_factory=PlanningPhaseConfiguration
    )
    project: str | None = None
    project_dir: str | None = None
    project_dir_resolution_attempted: bool = False
    interactive_just_enabled: bool = False
    hello_requested: bool = False
    is_cline_agent: bool = False
    pytest_compression_enabled: bool = True
    compress_next_tool_call_reply: bool = False
    pytest_compression_min_lines: int = 0
    planning_phase_turn_count: int = 0
    planning_phase_file_write_count: int = 0
    api_key_redaction_enabled: bool | None = None
    command_prefix_override: str | None = None

    def with_backend_config(self, backend_config: BackendConfiguration) -> SessionState:
        """Create a new session state with updated backend config."""
        return self.model_copy(update={"backend_config": backend_config})

    def with_reasoning_config(
        self, reasoning_config: ReasoningConfiguration
    ) -> SessionState:
        """Create a new session state with updated reasoning config."""
        return self.model_copy(update={"reasoning_config": reasoning_config})

    def with_loop_config(self, loop_config: LoopDetectionConfiguration) -> SessionState:
        """Create a new session state with updated loop config."""
        return self.model_copy(update={"loop_config": loop_config})

    def with_project(self, project: str | None) -> SessionState:
        """Create a new session state with updated project."""
        return self.model_copy(update={"project": project})

    def with_project_dir(self, project_dir: str | None) -> SessionState:
        """Create a new session state with updated project directory."""
        return self.model_copy(update={"project_dir": project_dir})

    def with_project_dir_resolution_attempted(self, attempted: bool) -> SessionState:
        """Create a new session state with updated resolution attempt flag."""
        return self.model_copy(update={"project_dir_resolution_attempted": attempted})

    def with_hello_requested(self, hello_requested: bool) -> SessionState:
        """Create a new session state with updated hello_requested flag."""
        return self.model_copy(update={"hello_requested": hello_requested})

    def with_interactive_just_enabled(self, enabled: bool) -> SessionState:
        """Create a new session state with updated interactive_just_enabled flag."""
        return self.model_copy(update={"interactive_just_enabled": enabled})

    def with_is_cline_agent(self, is_cline: bool) -> SessionState:
        """Create a new session state with updated is_cline_agent flag."""
        return self.model_copy(update={"is_cline_agent": is_cline})

    def with_pytest_compression_enabled(self, enabled: bool) -> SessionState:
        """Create a new session state with updated pytest_compression_enabled flag."""
        return self.model_copy(update={"pytest_compression_enabled": enabled})

    def with_compress_next_tool_call_reply(self, should_compress: bool) -> SessionState:
        """Create a new session state with updated compress_next_tool_call_reply flag."""
        return self.model_copy(
            update={"compress_next_tool_call_reply": should_compress}
        )

    def with_pytest_compression_min_lines(self, min_lines: int) -> SessionState:
        """Create a new session state with updated pytest_compression_min_lines value."""
        return self.model_copy(update={"pytest_compression_min_lines": min_lines})

    def with_planning_phase_config(
        self, planning_phase_config: PlanningPhaseConfiguration
    ) -> SessionState:
        """Create a new session state with updated planning phase config."""
        return self.model_copy(update={"planning_phase_config": planning_phase_config})

    def with_planning_phase_turn_count(self, count: int) -> SessionState:
        """Create a new session state with updated planning phase turn count."""
        return self.model_copy(update={"planning_phase_turn_count": count})

    def with_planning_phase_file_write_count(self, count: int) -> SessionState:
        """Create a new session state with updated planning phase file write count."""
        return self.model_copy(update={"planning_phase_file_write_count": count})

    def with_api_key_redaction_enabled(self, enabled: bool | None) -> SessionState:
        """Create a new session state with updated API key redaction flag."""
        return self.model_copy(update={"api_key_redaction_enabled": enabled})

    def with_command_prefix_override(
        self, command_prefix: str | None
    ) -> SessionState:
        """Create a new session state with a session-scoped command prefix override."""

        return self.model_copy(update={"command_prefix_override": command_prefix})


class SessionStateAdapter(ISessionState, ISessionStateMutator):
    """Adapter that makes SessionState implement ISessionState interface."""

    def __init__(self, session_state: SessionState):
        self._state: SessionState | ISessionState = session_state

    @property
    def backend_config(self) -> IBackendConfig:
        """Get the backend configuration."""
        return self._state.backend_config  # type: ignore[return-value]

    @property
    def reasoning_config(self) -> IReasoningConfig:
        """Get the reasoning configuration."""
        return self._state.reasoning_config  # type: ignore[return-value]

    @property
    def loop_config(self) -> ILoopDetectionConfig:
        """Get the loop detection configuration."""
        return self._state.loop_config  # type: ignore[return-value]

    @property
    def planning_phase_config(self) -> IPlanningPhaseConfig:
        """Get the planning phase configuration."""
        return self._state.planning_phase_config  # type: ignore[return-value]

    @property
    def project(self) -> str | None:
        """Get the project name."""
        return self._state.project

    @project.setter
    def project(self, value: str | None) -> None:
        """Set the project on the underlying state (mutating adapter)."""
        with contextlib.suppress(Exception):
            self._state = self._state.with_project(value)

    @property
    def project_dir(self) -> str | None:
        """Get the project directory."""
        return self._state.project_dir

    @project_dir.setter
    def project_dir(self, value: str | None) -> None:
        """Set the project_dir on the underlying state (mutating adapter)."""
        with contextlib.suppress(Exception):
            self._state = self._state.with_project_dir(value)

    @property
    def project_dir_resolution_attempted(self) -> bool:
        """Return whether automatic project directory detection was attempted."""
        return getattr(self._state, "project_dir_resolution_attempted", False)

    @project_dir_resolution_attempted.setter
    def project_dir_resolution_attempted(self, value: bool) -> None:
        """Set the project directory resolution attempted flag."""
        with contextlib.suppress(Exception):
            if hasattr(self._state, "with_project_dir_resolution_attempted"):
                self._state = self._state.with_project_dir_resolution_attempted(value)

    @property
    def interactive_mode(self) -> bool:
        """Whether interactive mode is enabled for this session (from backend_config)."""
        try:
            return bool(self._state.backend_config.interactive_mode)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Error checking interactive mode: {e}", exc_info=True)
            return False

    @property
    def interactive_just_enabled(self) -> bool:
        """Whether interactive mode was just enabled for this session."""
        return self._state.interactive_just_enabled

    @interactive_just_enabled.setter
    def interactive_just_enabled(self, value: bool) -> None:
        """Set the interactive_just_enabled flag on the underlying state."""
        with contextlib.suppress(Exception):
            self._state = self._state.with_interactive_just_enabled(value)

    @property
    def hello_requested(self) -> bool:
        """Whether hello was requested in this session."""
        return self._state.hello_requested

    @hello_requested.setter
    def hello_requested(self, value: bool) -> None:
        """Set the hello_requested flag on the underlying state."""
        with contextlib.suppress(Exception):
            self._state = self._state.with_hello_requested(value)

    @property
    def api_key_redaction_enabled(self) -> bool | None:
        """Get whether API key redaction is enabled for this session."""
        return getattr(self._state, "api_key_redaction_enabled", None)

    @api_key_redaction_enabled.setter
    def api_key_redaction_enabled(self, value: bool | None) -> None:
        """Set the API key redaction flag on the underlying state."""
        with contextlib.suppress(Exception):
            self._state = self._state.with_api_key_redaction_enabled(value)

    def with_api_key_redaction_enabled(self, enabled: bool | None) -> ISessionState:
        """Create a new session state with updated API key redaction flag."""
        # Type ignore needed due to interface compatibility issues
        if isinstance(self._state, SessionState):
            base_state = self._state  # type: ignore[assignment]
        else:
            base_state = SessionState.from_dict(self._state.to_dict())  # type: ignore[assignment]

        new_state = base_state.with_api_key_redaction_enabled(enabled)
        return SessionStateAdapter(new_state)  # type: ignore[arg-type]

    @property
    def command_prefix_override(self) -> str | None:
        """Get the session-specific command prefix override if configured."""
        value = getattr(self._state, "command_prefix_override", None)
        if isinstance(value, str):
            return value
        return None

    def with_command_prefix_override(
        self, command_prefix: str | None
    ) -> ISessionState:
        """Create a new session state adapter with updated command prefix override."""

        base_state: SessionState
        if isinstance(self._state, SessionState):
            base_state = self._state
        else:
            base_state = SessionState.from_dict(self._state.to_dict())

        new_state = base_state.with_command_prefix_override(command_prefix)
        return SessionStateAdapter(new_state)

    @property
    def is_cline_agent(self) -> bool:
        """Whether the agent is Cline for this session."""
        return self._state.is_cline_agent

    @property
    def pytest_compression_enabled(self) -> bool:
        """Whether pytest output compression is enabled for this session."""
        return self._state.pytest_compression_enabled

    @property
    def compress_next_tool_call_reply(self) -> bool:
        """Whether the next tool call reply should be compressed."""
        return self._state.compress_next_tool_call_reply

    @property
    def pytest_compression_min_lines(self) -> int:
        """Minimum line threshold for pytest compression."""
        return self._state.pytest_compression_min_lines

    @property
    def planning_phase_turn_count(self) -> int:
        """Number of turns completed in planning phase."""
        return self._state.planning_phase_turn_count

    @property
    def planning_phase_file_write_count(self) -> int:
        """Number of file writes completed in planning phase."""
        return self._state.planning_phase_file_write_count

    @property
    def override_model(self) -> str | None:
        """Get the override model from backend configuration."""
        # Use the property to ensure we get the value from model_value
        return self._state.backend_config.model

    @property
    def override_backend(self) -> str | None:
        """Get the override backend from backend configuration."""
        # Use the property to ensure we get the value from backend_type_value
        return self._state.backend_config.backend_type

    def equals(self, other: Any) -> bool:
        """Check if this value object equals another."""
        return self._state.equals(other)

    def to_dict(self) -> dict[str, Any]:
        """Convert this value object to a dictionary."""
        return self._state.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Create a SessionState from a dictionary."""
        # The superclass from_dict returns IValueObject, so we need to cast it to SessionState.
        return cast(SessionState, super().from_dict(data))

    def with_backend_config(self, config: IBackendConfig) -> ISessionState:
        """Create a new session state with updated backend config."""
        new_state = cast(SessionState, self._state).with_backend_config(
            cast(BackendConfiguration, config)
        )
        return SessionStateAdapter(new_state)

    def with_reasoning_config(self, config: IReasoningConfig) -> ISessionState:
        """Create a new session state with updated reasoning config."""
        new_state = cast(SessionState, self._state).with_reasoning_config(
            cast(ReasoningConfiguration, config)
        )
        return SessionStateAdapter(new_state)

    def with_loop_config(self, config: ILoopDetectionConfig) -> ISessionState:
        """Create a new session state with updated loop config."""
        new_state = cast(SessionState, self._state).with_loop_config(
            cast(LoopDetectionConfiguration, config)
        )
        return SessionStateAdapter(new_state)

    def with_project(self, project: str | None) -> ISessionState:
        """Create a new session state with updated project."""
        new_state = cast(SessionState, self._state).with_project(project)
        return SessionStateAdapter(new_state)

    def with_project_dir(self, project_dir: str | None) -> ISessionState:
        """Create a new session state with updated project directory."""
        new_state = cast(SessionState, self._state).with_project_dir(project_dir)
        return SessionStateAdapter(new_state)

    def with_interactive_just_enabled(self, enabled: bool) -> ISessionState:
        """Create a new session state with updated interactive_just_enabled flag."""
        new_state = cast(SessionState, self._state).with_interactive_just_enabled(
            enabled
        )
        return SessionStateAdapter(new_state)

    def with_hello_requested(self, hello_requested: bool) -> ISessionState:
        """Create a new session state with updated hello_requested flag."""
        new_state = cast(SessionState, self._state).with_hello_requested(
            hello_requested
        )
        return SessionStateAdapter(new_state)

    def with_is_cline_agent(self, is_cline: bool) -> ISessionState:
        """Create a new session state with updated is_cline_agent flag."""
        new_state = cast(SessionState, self._state).with_is_cline_agent(is_cline)
        return SessionStateAdapter(new_state)

    def with_pytest_compression_enabled(self, enabled: bool) -> ISessionState:
        """Create a new session state with updated pytest_compression_enabled flag."""
        new_state = cast(SessionState, self._state).with_pytest_compression_enabled(
            enabled
        )
        return SessionStateAdapter(new_state)

    def with_compress_next_tool_call_reply(
        self, should_compress: bool
    ) -> ISessionState:
        """Create a new session state with updated compress_next_tool_call_reply flag."""
        new_state = cast(SessionState, self._state).with_compress_next_tool_call_reply(
            should_compress
        )
        return SessionStateAdapter(new_state)

    def with_pytest_compression_min_lines(self, min_lines: int) -> ISessionState:
        """Create a new session state with updated pytest_compression_min_lines value."""
        new_state = cast(SessionState, self._state).with_pytest_compression_min_lines(
            min_lines
        )
        return SessionStateAdapter(new_state)

    def with_planning_phase_config(self, config: IPlanningPhaseConfig) -> ISessionState:
        """Create a new session state with updated planning phase config."""
        new_state = cast(SessionState, self._state).with_planning_phase_config(
            cast(PlanningPhaseConfiguration, config)
        )
        return SessionStateAdapter(new_state)

    def with_planning_phase_turn_count(self, count: int) -> ISessionState:
        """Create a new session state with updated planning phase turn count."""
        new_state = cast(SessionState, self._state).with_planning_phase_turn_count(
            count
        )
        return SessionStateAdapter(new_state)

    def with_planning_phase_file_write_count(self, count: int) -> ISessionState:
        """Create a new session state with updated planning phase file write count."""
        new_state = cast(
            SessionState, self._state
        ).with_planning_phase_file_write_count(count)
        return SessionStateAdapter(new_state)

    # Mutable convenience methods expected by legacy tests
    def set_project(self, project: str | None) -> None:
        """Set project on the underlying state (mutating adapter)."""
        self._state = self._state.with_project(project)

    def unset_project(self) -> None:
        """Unset project on the underlying state (mutating adapter)."""
        self.set_project(None)

    def set_project_dir(self, project_dir: str | None) -> None:
        """Set project_dir on the underlying state (mutating adapter)."""
        self._state = self._state.with_project_dir(project_dir)

    def unset_project_dir(self) -> None:
        """Unset project_dir on the underlying state (mutating adapter)."""
        self.set_project_dir(None)

    # Legacy override helpers (adapter exposes legacy property names used by tests)

    def set_override_model(self, backend: str, model: str) -> None:
        """Set an override backend/model pair on the session state."""
        new_backend_config = cast(
            BackendConfiguration, self._state.backend_config
        ).with_backend_and_model(backend, model)
        self._state = self._state.with_backend_config(
            cast(BackendConfiguration, new_backend_config)
        )

    def unset_override_model(self) -> None:
        """Clear any override backend/model on the session state."""
        new_backend_config = cast(
            BackendConfiguration, self._state.backend_config
        ).without_override()
        self._state = self._state.with_backend_config(
            cast(BackendConfiguration, new_backend_config)
        )


class Session(ISession):
    """Container for conversation state and history."""

    def get_model(self) -> str | None:
        """Get the current model from the backend configuration."""
        return self.state.backend_config.model

    def set_model(self, model: str) -> None:
        """Set the model on the session state."""
        new_backend_config = cast(
            BackendConfiguration, self.state.backend_config
        ).with_model(model)
        self.state = self.state.with_backend_config(new_backend_config)

    def set_provider(self, provider: str) -> None:
        """Set the provider on the session state."""
        new_backend_config = cast(
            BackendConfiguration, self.state.backend_config
        ).with_backend_type(provider)
        self.state = self.state.with_backend_config(new_backend_config)

    def set_reasoning_mode(self, mode: ReasoningMode) -> None:
        """Set the reasoning mode on the session state."""
        new_reasoning_config = cast(
            ReasoningConfiguration, self.state.reasoning_config
        ).model_copy(update=mode.model_dump(exclude_none=True))
        self.state = self.state.with_reasoning_config(new_reasoning_config)

    def get_reasoning_mode(self) -> IReasoningConfig:
        """Get the current reasoning mode from the session state."""
        return self.state.reasoning_config

    def __init__(
        self,
        session_id: str,
        state: ISessionState | SessionState | None = None,
        history: list[SessionInteraction] | None = None,
        created_at: datetime | None = None,
        last_active_at: datetime | None = None,
        agent: str | None = None,
    ) -> None:
        self._session_id: str = session_id
        self._state: ISessionState

        if state is None:
            self._state = SessionStateAdapter(SessionState())
        elif isinstance(state, SessionStateAdapter):
            self._state = state
        elif isinstance(state, SessionState):  # Handle raw SessionState directly
            self._state = SessionStateAdapter(state)
        else:  # Handle other ISessionState implementations by attempting conversion
            self._state = SessionStateAdapter(
                cast(SessionState, SessionState.from_dict(state.to_dict()))
            )

        self._history: list[SessionInteraction] = history or []
        self._created_at: datetime = created_at or datetime.now(timezone.utc)
        self._last_active_at: datetime = last_active_at or datetime.now(timezone.utc)
        self._agent: str | None = agent

    @property
    def id(self) -> str:
        """Get the unique identifier for this entity."""
        return self._session_id

    @property
    def session_id(self) -> str:
        """Get the session ID."""
        return self._session_id

    @property
    def state(self) -> ISessionState:
        """Get the session state."""
        return self._state

    @state.setter
    def state(self, value: ISessionState) -> None:
        """Set the session state."""
        if isinstance(value, SessionStateAdapter):
            self._state = value
        elif isinstance(  # type: ignore[unreachable]
            value, SessionState  # type: ignore[unreachable]
        ):  # Handle raw SessionState directly  # type: ignore[unreachable]  # type: ignore[unreachable]
            self._state = SessionStateAdapter(value)  # type: ignore[unreachable]
        else:  # Handle other ISessionState implementations by attempting conversion
            self._state = SessionStateAdapter(
                cast(SessionState, SessionState.from_dict(value.to_dict()))
            )
        self._last_active_at = datetime.now(timezone.utc)

    @property
    def history(self) -> list[Any]:
        """Get the session history."""
        return self._history

    @property
    def created_at(self) -> datetime:
        """Get the session creation time."""
        return self._created_at

    @property
    def last_active_at(self) -> datetime:
        """Get the time of last activity in this session."""
        return self._last_active_at

    @last_active_at.setter
    def last_active_at(self, value: datetime) -> None:
        """Set the time of last activity in this session."""
        self._last_active_at = value

    @property
    def agent(self) -> str | None:
        """Get the agent identifier for this session."""
        return self._agent

    @agent.setter
    def agent(self, value: str | None) -> None:
        """Set the agent identifier for this session."""
        self._agent = value

        # Update the is_cline_agent flag in the session state
        if value in ["cline", "roocode"]:
            logger.debug(f"Setting is_cline_agent to True for agent: {value}")
            self.state = self.state.with_is_cline_agent(True)
        else:
            logger.debug(f"Setting is_cline_agent to False for agent: {value}")
            self.state = self.state.with_is_cline_agent(False)

    @property
    def proxy_state(self) -> ISessionState:
        """Get the proxy state (backward compatibility alias for state)."""
        return self._state

    @property
    def is_cline_agent(self) -> bool:
        """Check if the agent for this session is Cline (from session state)."""
        return self.state.is_cline_agent

    def add_interaction(self, interaction: SessionInteraction) -> None:
        """Add an interaction to the session history."""
        self._history.append(interaction)
        self._last_active_at = datetime.now(timezone.utc)

    def update_state(self, state: ISessionState) -> None:
        """Update the session state."""
        if isinstance(state, SessionStateAdapter):  # type: ignore[unreachable]
            self._state = state
        elif isinstance(state, SessionState):  # type: ignore[unreachable]  # type: ignore[unreachable]
            self._state = SessionStateAdapter(state)  # type: ignore[unreachable]
        else:
            self._state = SessionStateAdapter(
                cast(SessionState, SessionState.from_dict(state.to_dict()))
            )
        self._last_active_at = datetime.now(timezone.utc)

    def equals(self, other: Any) -> bool:
        """Check if this entity equals another based on ID."""
        if not isinstance(other, ISession):
            return False
        return self.id == other.id

    def to_dict(self) -> dict[str, Any]:
        """Convert this session to a dictionary."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "state": self.state.to_dict() if self.state else None,
            "history": [
                h.model_dump() if hasattr(h, "model_dump") else h for h in self.history
            ],
            "created_at": self.created_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
            "agent": self.agent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        """Create a session from a dictionary."""
        state: SessionState | None = None
        if data.get("state"):
            state_value: SessionState = cast(
                SessionState, SessionState.from_dict(data["state"])
            )
            if isinstance(state_value, SessionState):
                state = state_value

        history: list[SessionInteraction] = []
        if data.get("history"):
            for h in data["history"]:
                if isinstance(h, dict):
                    history.append(SessionInteraction(**h))
                else:
                    history.append(h)

        # Convert ISO format strings to datetime objects
        created_at: datetime | None = None
        if data.get("created_at"):
            if isinstance(data["created_at"], str):
                created_at = datetime.fromisoformat(data["created_at"])
            else:
                created_at = data["created_at"]

        last_active_at: datetime | None = None
        if data.get("last_active_at"):
            if isinstance(data["last_active_at"], str):
                last_active_at = datetime.fromisoformat(data["last_active_at"])
            else:
                last_active_at = data["last_active_at"]

        return cls(
            session_id=data["session_id"],
            state=state,
            history=history,
            created_at=created_at,
            last_active_at=last_active_at,
            agent=data.get("agent"),
        )
