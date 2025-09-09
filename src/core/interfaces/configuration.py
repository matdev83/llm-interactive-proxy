"""
Configuration interfaces for the application.

This module defines interfaces for accessing configuration in a type-safe manner.
"""

from __future__ import annotations

import abc
from typing import Any


class IConfig(abc.ABC):
    """Interface for application configuration."""

    @abc.abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key.

        Args:
            key: The configuration key
            default: The default value if the key is not found

        Returns:
            The configuration value
        """

    @abc.abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.

        Args:
            key: The configuration key
            value: The configuration value
        """


class IAppIdentityConfig(abc.ABC):
    """Interface for application identity configuration."""

    @abc.abstractmethod
    def get_resolved_headers(
        self, incoming_headers: dict[str, Any] | None
    ) -> dict[str, str]:
        """Get the resolved headers for the application identity.

        Args:
            incoming_headers: The headers from the incoming request.

        Returns:
            A dictionary of resolved headers.
        """
        ...


class IBackendConfig(abc.ABC):
    """Interface for backend configuration."""

    @property
    @abc.abstractmethod
    def backend_type(self) -> str | None:
        """Get the backend type."""

    @property
    @abc.abstractmethod
    def model(self) -> str | None:
        """Get the model name."""

    @property
    @abc.abstractmethod
    def api_url(self) -> str | None:
        """Get the API URL."""

    @property
    @abc.abstractmethod
    def openai_url(self) -> str | None:
        """Get the OpenAI URL."""

    @property
    @abc.abstractmethod
    def interactive_mode(self) -> bool:
        """Get the interactive mode status."""

    @abc.abstractmethod
    def with_backend(self, backend_type: str | None) -> IBackendConfig:
        """Create a new config with updated backend type."""

    @abc.abstractmethod
    def with_model(self, model: str | None) -> IBackendConfig:
        """Create a new config with updated model."""

    @abc.abstractmethod
    def with_api_url(self, api_url: str | None) -> IBackendConfig:
        """Create a new config with updated API URL."""

    @abc.abstractmethod
    def with_openai_url(self, url: str | None) -> IBackendConfig:
        """Create a new config with updated OpenAI URL."""

    @abc.abstractmethod
    def with_interactive_mode(self, enabled: bool) -> IBackendConfig:
        """Create a new config with updated interactive mode."""

    @abc.abstractmethod
    def without_override(self) -> IBackendConfig:
        """Create a new config with cleared override settings."""

    @abc.abstractmethod
    def with_oneoff_route(self, backend: str, model: str) -> IBackendConfig:
        """Create a new config with a one-off route for the next request."""

    @abc.abstractmethod
    def with_failover_route(self, name: str, policy: str) -> IBackendConfig:
        """Create a new config with a new failover route."""

    @abc.abstractmethod
    def without_failover_route(self, name: str) -> IBackendConfig:
        """Create a new config with a failover route removed."""

    @abc.abstractmethod
    def with_cleared_route(self, name: str) -> IBackendConfig:
        """Create a new config with a cleared failover route."""

    @abc.abstractmethod
    def with_appended_route_element(self, name: str, element: str) -> IBackendConfig:
        """Create a new config with an element appended to a failover route."""

    @abc.abstractmethod
    def with_prepended_route_element(self, name: str, element: str) -> IBackendConfig:
        """Create a new config with an element prepended to a failover route."""

    @abc.abstractmethod
    def get_route_elements(self, name: str) -> list[str]:
        """Get elements of a failover route."""

    @property
    @abc.abstractmethod
    def failover_routes(self) -> dict[str, dict[str, Any]]:
        """Get the failover routes."""


class IReasoningConfig(abc.ABC):
    """Interface for reasoning configuration."""

    @property
    @abc.abstractmethod
    def reasoning_effort(self) -> str | None:
        """Get the reasoning effort level."""

    @property
    @abc.abstractmethod
    def thinking_budget(self) -> int | None:
        """Get the thinking budget."""

    @property
    @abc.abstractmethod
    def temperature(self) -> float | None:
        """Get the temperature."""

    @property
    @abc.abstractmethod
    def gemini_generation_config(self) -> dict[str, Any] | None:
        """Get the Gemini generation configuration."""

    @abc.abstractmethod
    def with_reasoning_effort(self, effort: str | None) -> IReasoningConfig:
        """Create a new config with updated reasoning effort."""

    @abc.abstractmethod
    def with_thinking_budget(self, budget: int | None) -> IReasoningConfig:
        """Create a new config with updated thinking budget."""

    @abc.abstractmethod
    def with_temperature(self, temperature: float | None) -> IReasoningConfig:
        """Create a new config with updated temperature."""

    @abc.abstractmethod
    def with_gemini_generation_config(
        self, config: dict[str, Any] | None
    ) -> IReasoningConfig:
        """Create a new config with updated Gemini generation configuration."""


class ILoopDetectionConfig(abc.ABC):
    """Interface for loop detection configuration."""

    @property
    @abc.abstractmethod
    def loop_detection_enabled(self) -> bool:
        """Get whether loop detection is enabled."""

    @property
    @abc.abstractmethod
    def tool_loop_detection_enabled(self) -> bool:
        """Get whether tool loop detection is enabled."""

    @abc.abstractmethod
    def with_loop_detection_enabled(self, enabled: bool) -> ILoopDetectionConfig:
        """Create a new config with updated loop detection enabled status."""

    @abc.abstractmethod
    def with_tool_loop_detection_enabled(self, enabled: bool) -> ILoopDetectionConfig:
        """Create a new config with updated tool loop detection enabled status."""

    @abc.abstractmethod
    def with_tool_loop_max_repeats(
        self, max_repeats: int | None
    ) -> ILoopDetectionConfig:
        """Create a new config with updated tool loop max repeats."""

    @abc.abstractmethod
    def with_tool_loop_ttl(self, ttl: int | None) -> ILoopDetectionConfig:
        """Create a new config with updated tool loop TTL."""

    @abc.abstractmethod
    def with_tool_loop_ttl_seconds(self, ttl_seconds: int) -> ILoopDetectionConfig:
        """Create a new config with updated tool loop TTL seconds."""

    @abc.abstractmethod
    def with_tool_loop_mode(self, mode: str | None) -> ILoopDetectionConfig:
        """Create a new config with updated tool loop mode."""


class IBackendSpecificConfig(abc.ABC):
    """Interface for backend-specific configuration."""

    @abc.abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary for the API.

        Returns:
            Dictionary representation of the configuration
        """
