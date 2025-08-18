from __future__ import annotations

import logging
from typing import Any

from pydantic import field_validator

from src.core.domain.base import ValueObject
from src.core.interfaces.configuration_interface import IBackendConfig

logger = logging.getLogger(__name__)


class BackendConfiguration(ValueObject, IBackendConfig):
    """Configuration for backend services.

    This class handles backend and model selection, API URLs, and failover routes.
    It replaces the backend-related functionality of ProxyState.
    """

    backend_type: str | None = None
    model: str | None = None
    api_url: str | None = None
    _interactive_mode: bool = True
    _failover_routes: dict[str, dict[str, Any]] = {}

    @property
    def interactive_mode(self) -> bool:
        """Get whether interactive mode is enabled."""
        return self._interactive_mode

    @property
    def failover_routes(self) -> dict[str, dict[str, Any]]:
        """Get the failover routes."""
        return self._failover_routes

    # One-time override for next request
    oneoff_backend: str | None = None
    oneoff_model: str | None = None

    # Override validation
    invalid_override: bool = False

    # OpenAI-specific settings
    openai_url: str | None = None

    @classmethod
    @field_validator("openai_url")
    def validate_openai_url(cls, v: str | None) -> str | None:
        """Validate that the OpenAI URL is properly formatted."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("OpenAI URL must start with http:// or https://")
        return v

    def with_backend(self, backend_type: str | None) -> IBackendConfig:
        """Create a new config with updated backend type."""
        return self.model_copy(
            update={
                "backend_type": backend_type,
                # Keep existing model when changing backend
                "invalid_override": False,
            }
        )

    def with_model(self, model: str | None) -> IBackendConfig:
        """Create a new config with updated model."""
        return self.model_copy(update={"model": model})

    def with_api_url(self, api_url: str | None) -> IBackendConfig:
        """Create a new config with updated API URL."""
        return self.model_copy(update={"api_url": api_url})

    def with_openai_url(self, url: str | None) -> IBackendConfig:
        """Create a new config with updated OpenAI URL."""
        return self.model_copy(update={"openai_url": url})

    def with_interactive_mode(self, enabled: bool) -> IBackendConfig:
        """Create a new config with updated interactive mode."""
        return self.model_copy(update={"_interactive_mode": enabled})

    def with_backend_and_model(
        self, backend: str, model: str, invalid: bool = False
    ) -> IBackendConfig:
        """Create a new config with updated backend and model."""
        return self.model_copy(
            update={
                "backend_type": backend,
                "model": model,
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
                "backend_type": None,
                "model": None,
                "api_url": None,
                "oneoff_backend": None,
                "oneoff_model": None,
                "invalid_override": False,
            }
        )

    # Failover route management
    def with_failover_route(self, name: str, policy: str) -> IBackendConfig:
        """Create a new config with a new failover route."""
        new_routes = dict(self._failover_routes)
        new_routes[name] = {"policy": policy, "elements": []}
        return self.model_copy(update={"_failover_routes": new_routes})

    def without_failover_route(self, name: str) -> IBackendConfig:
        """Create a new config with a failover route removed."""
        new_routes = dict(self._failover_routes)
        new_routes.pop(name, None)
        return self.model_copy(update={"_failover_routes": new_routes})

    def with_cleared_route(self, name: str) -> IBackendConfig:
        """Create a new config with a cleared failover route."""
        new_routes = dict(self._failover_routes)
        if name in new_routes:
            new_routes[name] = {**new_routes[name], "elements": []}
        return self.model_copy(update={"_failover_routes": new_routes})

    def with_appended_route_element(self, name: str, element: str) -> IBackendConfig:
        """Create a new config with an element appended to a failover route."""
        new_routes = dict(self._failover_routes)
        route = new_routes.setdefault(name, {"policy": "k", "elements": []})
        elements = list(route.get("elements", []))
        elements.append(element)
        route["elements"] = elements
        return self.model_copy(update={"_failover_routes": new_routes})

    def with_prepended_route_element(self, name: str, element: str) -> IBackendConfig:
        """Create a new config with an element prepended to a failover route."""
        new_routes = dict(self._failover_routes)
        route = new_routes.setdefault(name, {"policy": "k", "elements": []})
        elements = list(route.get("elements", []))
        elements.insert(0, element)
        route["elements"] = elements
        return self.model_copy(update={"_failover_routes": new_routes})

    # Utility methods
    def get_route_elements(self, name: str) -> list[str]:
        """Get elements of a failover route."""
        route = self._failover_routes.get(name)
        if route is None:
            return []
        return list(route.get("elements", []))

    def get_routes(self) -> dict[str, str]:
        """Get all route names and policies."""
        return {n: r.get("policy", "") for n, r in self._failover_routes.items()}
