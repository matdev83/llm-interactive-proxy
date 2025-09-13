from __future__ import annotations

import abc
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from src.core.interfaces.configuration_interface import (
    IBackendConfig,
    ILoopDetectionConfig,
    IReasoningConfig,
)


class IEntity(ABC):
    """Base interface for domain entities.

    All domain entities should have a unique identifier.
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """Get the unique identifier for this entity."""


class IValueObject(ABC):
    """Base interface for value objects.

    Value objects are immutable and compared by their attributes,
    not by identity.
    """

    @abstractmethod
    def equals(self, other: Any) -> bool:
        """Check if this value object equals another.

        Args:
            other: Another value object to compare with

        Returns:
            True if the value objects are equal
        """

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Convert this value object to a dictionary.

        Returns:
            Dictionary representation of this value object
        """

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> IValueObject:
        """Create a value object from a dictionary.

        Args:
            data: Dictionary representation of a value object

        Returns:
            A new value object
        """


class ISession(IEntity):
    """Interface for session entities."""

    @property
    @abstractmethod
    def session_id(self) -> str:
        """Get the session ID."""

    @property
    @abstractmethod
    def state(self) -> ISessionState:
        """Get the session state."""

    @property
    @abstractmethod
    def history(self) -> list[Any]:
        """Get the session history."""

    @property
    @abstractmethod
    def created_at(self) -> datetime:
        """Get the session creation time."""

    @property
    @abstractmethod
    def last_active_at(self) -> datetime:
        """Get the time of last activity in this session."""

    @property
    @abstractmethod
    def agent(self) -> str | None:
        """Get the agent identifier for this session."""

    @abstractmethod
    def add_interaction(self, interaction: Any) -> None:
        """Add an interaction to the session history.

        Args:
            interaction: The interaction to add
        """

    @abstractmethod
    def update_state(self, state: ISessionState) -> None:
        """Update the session state.

        Args:
            state: The new session state
        """


class ISessionStateMutator(ABC):
    """Interface for session state mutator methods."""

    @abc.abstractmethod
    def with_is_cline_agent(self, is_cline: bool) -> ISessionState:
        """Create a new state with updated is_cline_agent flag."""


class ISessionState(IValueObject, ISessionStateMutator):
    """Interface for session state value objects."""

    @property
    @abstractmethod
    def backend_config(self) -> IBackendConfig:
        """Get the backend configuration."""

    @property
    @abstractmethod
    def reasoning_config(self) -> IReasoningConfig:
        """Get the reasoning configuration."""

    @property
    @abstractmethod
    def loop_config(self) -> ILoopDetectionConfig:
        """Get the loop detection configuration."""

    @property
    @abstractmethod
    def project(self) -> str | None:
        """Get the project name."""

    @property
    @abstractmethod
    def project_dir(self) -> str | None:
        """Get the project directory."""

    @abc.abstractmethod
    def with_backend_config(self, config: IBackendConfig) -> ISessionState:
        """Create a new state with updated backend configuration."""

    @abc.abstractmethod
    def with_reasoning_config(self, config: IReasoningConfig) -> ISessionState:
        """Create a new state with updated reasoning configuration."""

    @abc.abstractmethod
    def with_loop_config(self, config: ILoopDetectionConfig) -> ISessionState:
        """Create a new state with updated loop detection configuration."""

    @abc.abstractmethod
    def with_project(self, project: str | None) -> ISessionState:
        """Create a new state with updated project name."""

    @abc.abstractmethod
    def with_project_dir(self, project_dir: str | None) -> ISessionState:
        """Create a new state with updated project directory."""

    @property
    @abc.abstractmethod
    def interactive_just_enabled(self) -> bool:
        """Get whether interactive mode was just enabled."""

    @abc.abstractmethod
    def with_interactive_just_enabled(self, enabled: bool) -> ISessionState:
        """Create a new state with updated interactive_just_enabled flag."""

    @property
    @abc.abstractmethod
    def hello_requested(self) -> bool:
        """Get whether hello was requested in this session."""

    @hello_requested.setter
    @abc.abstractmethod
    def hello_requested(self, value: bool) -> None:
        """Set whether hello was requested in this session."""

    @abc.abstractmethod
    def with_hello_requested(self, hello_requested: bool) -> ISessionState:
        """Create a new state with updated hello_requested flag."""

    @property
    @abc.abstractmethod
    def is_cline_agent(self) -> bool:
        """Get whether the current agent is a CLI agent."""

    @property
    @abc.abstractmethod
    def override_model(self) -> str | None:
        """Get the override model from backend configuration."""

    @property
    @abc.abstractmethod
    def override_backend(self) -> str | None:
        """Get the override backend from backend configuration."""

    @property
    @abc.abstractmethod
    def pytest_compression_enabled(self) -> bool:
        """Get whether pytest output compression is enabled for this session."""

    @abc.abstractmethod
    def with_pytest_compression_enabled(self, enabled: bool) -> ISessionState:
        """Create a new state with updated pytest_compression_enabled flag."""
