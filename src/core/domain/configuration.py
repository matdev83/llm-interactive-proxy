from __future__ import annotations

from typing import Any, cast

from pydantic import Field

from src.core.domain.base import ValueObject
from src.core.interfaces.configuration_interface import (
    IBackendConfig,
    ILoopDetectionConfig,
    IReasoningConfig,
)


class BackendConfig(ValueObject):
    """Configuration for backend services."""

    backend_type: str | None = None
    model: str | None = None
    api_url: str | None = None
    openai_url: str | None = None
    interactive_mode: bool = True
    failover_routes: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def with_backend(self, backend_type: str | None) -> IBackendConfig:
        """Create a new config with updated backend type."""
        return cast(
            IBackendConfig, self.model_copy(update={"backend_type": backend_type})
        )

    def with_model(self, model: str | None) -> IBackendConfig:
        """Create a new config with updated model."""
        return cast(IBackendConfig, self.model_copy(update={"model": model}))

    def with_api_url(self, api_url: str | None) -> IBackendConfig:
        """Create a new config with updated API URL."""
        return cast(IBackendConfig, self.model_copy(update={"api_url": api_url}))

    def with_openai_url(self, url: str | None) -> IBackendConfig:
        """Create a new config with updated OpenAI URL."""
        return cast(IBackendConfig, self.model_copy(update={"openai_url": url}))

    def with_interactive_mode(self, enabled: bool) -> IBackendConfig:
        """Create a new config with updated interactive mode."""
        return cast(
            IBackendConfig, self.model_copy(update={"interactive_mode": enabled})
        )

    def without_override(self) -> IBackendConfig:
        """Create a new config with cleared override settings."""
        return cast(
            IBackendConfig,
            self.model_copy(update={"backend_type": None, "model": None}),
        )

    def with_oneoff_route(self, backend: str, model: str) -> IBackendConfig:
        """Create a new config with a one-off route for the next request."""
        # For now, just store as backend/model override
        return cast(
            IBackendConfig,
            self.model_copy(update={"backend_type": backend, "model": model}),
        )

    def with_failover_route(self, name: str, policy: str) -> IBackendConfig:
        """Create a new config with a new failover route."""
        routes: dict[str, dict[str, Any]] = self.failover_routes.copy()
        routes[name] = {"policy": policy, "elements": []}
        return cast(IBackendConfig, self.model_copy(update={"failover_routes": routes}))

    def without_failover_route(self, name: str) -> IBackendConfig:
        """Create a new config with a failover route removed."""
        routes: dict[str, dict[str, Any]] = self.failover_routes.copy()
        routes.pop(name, None)
        return cast(IBackendConfig, self.model_copy(update={"failover_routes": routes}))

    def with_cleared_route(self, name: str) -> IBackendConfig:
        """Create a new config with a cleared failover route."""
        routes: dict[str, dict[str, Any]] = self.failover_routes.copy()
        if name in routes:
            routes[name] = {"policy": routes[name].get("policy", "k"), "elements": []}
        return cast(IBackendConfig, self.model_copy(update={"failover_routes": routes}))

    def with_appended_route_element(self, name: str, element: str) -> IBackendConfig:
        """Create a new config with an element appended to a failover route."""
        routes: dict[str, dict[str, Any]] = self.failover_routes.copy()
        if name in routes:
            elements: list[str] = routes[name].get("elements", [])
            elements = [*elements, element] if isinstance(elements, list) else [element]
            routes[name]["elements"] = elements
        return cast(IBackendConfig, self.model_copy(update={"failover_routes": routes}))

    def with_prepended_route_element(self, name: str, element: str) -> IBackendConfig:
        """Create a new config with an element prepended to a failover route."""
        routes: dict[str, dict[str, Any]] = self.failover_routes.copy()
        if name in routes:
            elements: list[str] = routes[name].get("elements", [])
            elements = [element, *elements] if isinstance(elements, list) else [element]
            routes[name]["elements"] = elements
        return cast(IBackendConfig, self.model_copy(update={"failover_routes": routes}))

    def get_route_elements(self, name: str) -> list[str]:
        """Get elements of a failover route."""
        route: dict[str, Any] = self.failover_routes.get(name, {})
        elements: list[Any] = route.get("elements", [])
        return list(elements) if isinstance(elements, list) else []


class ReasoningConfig(ValueObject, IReasoningConfig):
    """Configuration for reasoning parameters."""

    reasoning_effort: str | None = None
    thinking_budget: int | None = None
    temperature: float | None = None

    def with_reasoning_effort(self, effort: str | None) -> IReasoningConfig:
        """Create a new config with updated reasoning effort."""
        return self.model_copy(update={"reasoning_effort": effort})

    def with_thinking_budget(self, budget: int | None) -> IReasoningConfig:
        """Create a new config with updated thinking budget."""
        return self.model_copy(update={"thinking_budget": budget})

    def with_temperature(self, temperature: float | None) -> IReasoningConfig:
        """Create a new config with updated temperature."""
        return self.model_copy(update={"temperature": temperature})


class LoopDetectionConfig(ValueObject, ILoopDetectionConfig):
    """Configuration for loop detection."""

    loop_detection_enabled: bool = True
    tool_loop_detection_enabled: bool = True
    min_pattern_length: int = 100  # Based on memory ID 3368303
    max_pattern_length: int = 8000  # Based on memory ID 3368303

    def with_loop_detection_enabled(self, enabled: bool) -> ILoopDetectionConfig:
        """Create a new config with updated loop detection enabled flag."""
        return self.model_copy(update={"loop_detection_enabled": enabled})

    def with_tool_loop_detection_enabled(self, enabled: bool) -> ILoopDetectionConfig:
        """Create a new config with updated tool loop detection enabled flag."""
        return self.model_copy(update={"tool_loop_detection_enabled": enabled})

    def with_pattern_length_range(
        self, min_length: int, max_length: int
    ) -> ILoopDetectionConfig:
        """Create a new config with updated pattern length range."""
        return self.model_copy(
            update={"min_pattern_length": min_length, "max_pattern_length": max_length}
        )
