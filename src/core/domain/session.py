from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any, cast

from pydantic import ConfigDict, Field

from src.core.domain.base import ValueObject
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.interfaces.configuration_interface import (
    IBackendConfig,
    ILoopDetectionConfig,
    IReasoningConfig,
)
from src.core.interfaces.domain_entities_interface import ISession, ISessionState


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
    project: str | None = None
    project_dir: str | None = None
    interactive_just_enabled: bool = False
    hello_requested: bool = False
    is_cline_agent: bool = False

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

    def with_hello_requested(self, hello_requested: bool) -> SessionState:
        """Create a new session state with updated hello_requested flag."""
        return self.model_copy(update={"hello_requested": hello_requested})

    def with_interactive_just_enabled(self, enabled: bool) -> SessionState:
        """Create a new session state with updated interactive_just_enabled flag."""
        return self.model_copy(update={"interactive_just_enabled": enabled})


class SessionStateAdapter(ISessionState):
    """Adapter that makes SessionState implement ISessionState interface."""

    def __init__(self, session_state: SessionState):
        self._state = session_state

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
    def interactive_mode(self) -> bool:
        """Whether interactive mode is enabled for this session (from backend_config)."""
        try:
            return bool(self._state.backend_config.interactive_mode)
        except Exception:
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
    def is_cline_agent(self) -> bool:
        """Whether the agent is Cline for this session."""
        return self._state.is_cline_agent

    @property
    def override_model(self) -> str | None:
        """Get the override model from backend configuration."""
        return self._state.backend_config.model

    @property
    def override_backend(self) -> str | None:
        """Get the override backend from backend configuration."""
        return self._state.backend_config.backend_type

    def equals(self, other: Any) -> bool:
        """Check if this value object equals another."""
        return self._state.equals(other)

    def to_dict(self) -> dict[str, Any]:
        """Convert this value object to a dictionary."""
        return self._state.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ISessionState:
        """Create a value object from a dictionary."""
        state = SessionState.from_dict(data)
        return cls(state)  # type: ignore

    def with_backend_config(self, config: IBackendConfig) -> ISessionState:
        """Create a new session state with updated backend config."""
        new_state = self._state.with_backend_config(
            cast(BackendConfiguration, config)
        )
        return SessionStateAdapter(new_state)

    def with_reasoning_config(
        self, config: IReasoningConfig
    ) -> ISessionState:
        """Create a new session state with updated reasoning config."""
        new_state = self._state.with_reasoning_config(
            cast(ReasoningConfiguration, config)
        )
        return SessionStateAdapter(new_state)

    def with_loop_config(self, config: ILoopDetectionConfig) -> ISessionState:
        """Create a new session state with updated loop config."""
        new_state = self._state.with_loop_config(
            cast(LoopDetectionConfiguration, config)
        )
        return SessionStateAdapter(new_state)

    def with_project(self, project: str | None) -> ISessionState:
        """Create a new session state with updated project."""
        new_state = self._state.with_project(project)
        return SessionStateAdapter(new_state)

    def with_project_dir(self, project_dir: str | None) -> ISessionState:
        """Create a new session state with updated project directory."""
        new_state = self._state.with_project_dir(project_dir)
        return SessionStateAdapter(new_state)

    def with_interactive_just_enabled(self, enabled: bool) -> ISessionState:
        """Create a new session state with updated interactive_just_enabled flag."""
        new_state = self._state.with_interactive_just_enabled(enabled)
        return SessionStateAdapter(new_state)

    def with_hello_requested(self, hello_requested: bool) -> ISessionState:
        """Create a new session state with updated hello_requested flag."""
        new_state = self._state.with_hello_requested(hello_requested)
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
        new_backend_config = self._state.backend_config.with_backend_and_model(
            backend, model
        )
        self._state = self._state.with_backend_config(
            cast(BackendConfiguration, new_backend_config)
        )

    def unset_override_model(self) -> None:
        """Clear any override backend/model on the session state."""
        new_backend_config = self._state.backend_config.without_override()
        self._state = self._state.with_backend_config(
            cast(BackendConfiguration, new_backend_config)
        )


class Session(ISession):
    """Container for conversation state and history."""

    def __init__(
        self,
        session_id: str,
        state: ISessionState | SessionState | None = None,
        history: list[SessionInteraction] | None = None,
        created_at: datetime | None = None,
        last_active_at: datetime | None = None,
        agent: str | None = None,
    ):
        self._session_id = session_id
        self._state: ISessionState  # Type annotation fix

        # Handle different state types
        if state is None:
            self._state = SessionStateAdapter(SessionState())
        elif isinstance(state, SessionState):
            self._state = SessionStateAdapter(state)
        else:
            self._state = state

        self._history = history or []
        self._created_at = created_at or datetime.now(timezone.utc)
        self._last_active_at = last_active_at or datetime.now(timezone.utc)
        self._agent = agent

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
        # If we currently hold a SessionStateAdapter and are being assigned a
        # new adapter or a concrete SessionState, mutate the existing adapter's
        # internal state in-place so external holders of the adapter observe the
        # update. This preserves identity for callers (tests) that passed the
        # adapter object around.
        if isinstance(self._state, object) and isinstance(
            self._state, SessionStateAdapter
        ):
            # Mutate in-place if possible
            try:
                if isinstance(value, SessionStateAdapter):
                    self._state._state = value._state
                elif isinstance(value, SessionState):
                    self._state._state = value
                else:
                    # Best-effort: try to copy dict representation
                    try:
                        new_state = SessionState.from_dict(value.to_dict())
                        self._state._state = new_state  # type: ignore
                    except Exception:
                        # Fallback to replacing the adapter reference
                        self._state = value
            except Exception:
                self._state = value
        else:
            self._state = value

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
        if (value == "cline" or value == "roocode") and isinstance(
            self._state, SessionStateAdapter
        ):
            # Get the current state
            current_state = self._state._state
            # Create a new state with is_cline_agent=True
            new_state = SessionState(
                backend_config=current_state.backend_config,
                reasoning_config=current_state.reasoning_config,
                loop_config=current_state.loop_config,
                project=current_state.project,
                project_dir=current_state.project_dir,
                interactive_just_enabled=current_state.interactive_just_enabled,
                hello_requested=current_state.hello_requested,
                is_cline_agent=True,
            )
            # Update the state
            self._state = SessionStateAdapter(new_state)

    @property
    def proxy_state(self) -> ISessionState:
        """Get the proxy state (backward compatibility alias for state)."""
        return self._state

    def add_interaction(self, interaction: SessionInteraction) -> None:
        """Add an interaction to the session history."""
        self._history.append(interaction)
        self._last_active_at = datetime.now(timezone.utc)

    def update_state(self, state: ISessionState) -> None:
        """Update the session state."""
        # Prefer mutating existing adapter in-place so external holders of the
        # adapter observe changes. Fall back to replacing the reference.
        if isinstance(self._state, SessionStateAdapter):
            # If caller provided an adapter, copy its concrete state into ours
            if isinstance(state, SessionStateAdapter):
                self._state._state = state._state
            elif isinstance(state, SessionState):
                self._state._state = state
            else:
                # Try to convert via to_dict/from_dict
                try:
                    new_state = SessionState.from_dict(state.to_dict())
                    self._state._state = new_state  # type: ignore
                except Exception:
                    self._state = state
        else:
            self._state = state
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
        state = None
        if data.get("state"):
            state_value = SessionState.from_dict(data["state"])
            if isinstance(state_value, SessionState):
                state = state_value

        history = []
        if data.get("history"):
            for h in data["history"]:
                if isinstance(h, dict):
                    history.append(SessionInteraction(**h))
                else:
                    history.append(h)

        # Convert ISO format strings to datetime objects
        created_at = None
        if data.get("created_at"):
            if isinstance(data["created_at"], str):
                created_at = datetime.fromisoformat(data["created_at"])
            else:
                created_at = data["created_at"]

        last_active_at = None
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
