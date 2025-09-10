from __future__ import annotations

import logging
from typing import Any

from pydantic import Field, field_validator

from src.core.domain.base import ValueObject
from src.core.interfaces.configuration import IBackendConfig

logger = logging.getLogger(__name__)


class BackendConfiguration(ValueObject, IBackendConfig):
    """Configuration for backend services.

    This class handles backend and model selection, API URLs, and failover routes.
    It replaces the backend-related functionality of ProxyState.
    """

    # Primary fields with aliases for interface compatibility
    backend_type_value: str | None = Field(default=None, alias="backend_type")
    model_value: str | None = Field(default=None, alias="model")
    api_url_value: str | None = Field(default=None, alias="api_url")
    interactive_mode_value: bool = Field(default=True, alias="interactive_mode")
    failover_routes_data: dict[str, dict[str, Any]] = Field(default_factory=dict)
    openai_url_value: str | None = Field(default=None, alias="openai_url")

    @property
    def backend_type(self) -> str | None:
        """Get the backend type."""
        return self.backend_type_value

    @property
    def model(self) -> str | None:
        """Get the model name."""
        return self.model_value

    @property
    def api_url(self) -> str | None:
        """Get the API URL."""
        return self.api_url_value

    @property
    def openai_url(self) -> str | None:
        """Get the OpenAI URL."""
        return self.openai_url_value

    @property
    def interactive_mode(self) -> bool:
        """Get whether interactive mode is enabled."""
        return self.interactive_mode_value

    @property
    def failover_routes(self) -> dict[str, dict[str, Any]]:
        """Get the failover routes."""
        return self.failover_routes_data

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Override model_dump to include property values.

        This ensures that tests using model_dump() to access properties work correctly.
        """
        result = super().model_dump(**kwargs)
        # Add property values to the result
        result["backend_type"] = self.backend_type
        result["model"] = self.model
        result["api_url"] = self.api_url
        result["openai_url"] = self.openai_url
        result["interactive_mode"] = self.interactive_mode
        result["failover_routes"] = self.failover_routes
        return result

    # One-time override for next request
    oneoff_backend: str | None = None
    oneoff_model: str | None = None

    # Override validation
    invalid_override: bool = False

    @classmethod
    @field_validator("openai_url_value")
    def validate_openai_url(cls, v: str | None) -> str | None:
        """Validate that the OpenAI URL is properly formatted."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("OpenAI URL must start with http:// or https://")
        return v

    def with_backend(self, backend_type: str | None) -> IBackendConfig:
        """Create a new config with updated backend type."""
        return self.model_copy(
            update={
                "backend_type_value": backend_type,
                # Keep existing model when changing backend
                "invalid_override": False,
            }
        )

    def with_model(self, model: str | None) -> IBackendConfig:
        """Create a new config with updated model."""
        return self.model_copy(update={"model_value": model})

    def with_api_url(self, api_url: str | None) -> IBackendConfig:
        """Create a new config with updated API URL."""
        return self.model_copy(update={"api_url_value": api_url})

    def with_openai_url(self, url: str | None) -> IBackendConfig:
        """Create a new config with updated OpenAI URL."""
        return self.model_copy(update={"openai_url_value": url})

    def with_interactive_mode(self, enabled: bool) -> IBackendConfig:
        """Create a new config with updated interactive mode."""
        return self.model_copy(update={"interactive_mode_value": enabled})

    def with_backend_and_model(
        self, backend: str, model: str, invalid: bool = False
    ) -> IBackendConfig:
        """Create a new config with updated backend and model."""
        return self.model_copy(
            update={
                "backend_type_value": backend,
                "model_value": model,
                "invalid_override": invalid,
            }
        )

    def with_oneoff_route(self, backend: str, model: str) -> IBackendConfig:
        """Create a new config with a one-off route for the next request."""
        return self.model_copy(
            update={"oneoff_backend": backend, "oneoff_model": model}
        )

    def without_oneoff_route(self) -> IBackendConfig:
        """Create a new config with cleared one-off route."""
        return self.model_copy(update={"oneoff_backend": None, "oneoff_model": None})

    def without_override(self) -> IBackendConfig:
        """Create a new config with cleared override settings."""
        return self.model_copy(
            update={
                "backend_type_value": None,
                "model_value": None,
                "api_url_value": None,
                "oneoff_backend": None,
                "oneoff_model": None,
                "invalid_override": False,
            }
        )

    # Failover route management
    def with_failover_route(self, name: str, policy: str) -> IBackendConfig:
        """Create a new config with a new failover route."""
        new_routes: dict[str, dict[str, Any]] = dict(self.failover_routes_data)
        new_routes[name] = {"policy": policy, "elements": []}
        return self.model_copy(update={"failover_routes_data": new_routes})

    def without_failover_route(self, name: str) -> IBackendConfig:
        """Create a new config with a failover route removed."""
        new_routes: dict[str, dict[str, Any]] = dict(self.failover_routes_data)
        new_routes.pop(name, None)
        return self.model_copy(update={"failover_routes_data": new_routes})

    def with_cleared_route(self, name: str) -> IBackendConfig:
        """Create a new config with a cleared failover route."""
        new_routes: dict[str, dict[str, Any]] = dict(self.failover_routes_data)
        if name in new_routes:
            new_routes[name] = {**new_routes[name], "elements": []}
        return self.model_copy(update={"failover_routes_data": new_routes})

    def with_appended_route_element(self, name: str, element: str) -> IBackendConfig:
        """Create a new config with an element appended to a failover route."""
        new_routes: dict[str, dict[str, Any]] = dict(self.failover_routes_data)
        route: dict[str, Any] = new_routes.setdefault(
            name, {"policy": "k", "elements": []}
        )
        elements: list[str] = list(route.get("elements", []))
        elements.append(element)
        route["elements"] = elements
        return self.model_copy(update={"failover_routes_data": new_routes})

    def with_prepended_route_element(self, name: str, element: str) -> IBackendConfig:
        """Create a new config with an element prepended to a failover route."""
        new_routes: dict[str, dict[str, Any]] = dict(self.failover_routes_data)
        route: dict[str, Any] = new_routes.setdefault(
            name, {"policy": "k", "elements": []}
        )
        elements: list[str] = list(route.get("elements", []))
        elements.insert(0, element)
        route["elements"] = elements
        return self.model_copy(update={"failover_routes_data": new_routes})

    # Utility methods
    def get_route_elements(self, name: str) -> list[str]:
        """Get elements of a failover route."""
        route: dict[str, Any] | None = self.failover_routes_data.get(name)
        if route is None:
            return []
        return list(route.get("elements", []))

    def get_routes(self) -> dict[str, str]:
        """Get all route names and policies."""
        return {n: r.get("policy", "") for n, r in self.failover_routes_data.items()}
