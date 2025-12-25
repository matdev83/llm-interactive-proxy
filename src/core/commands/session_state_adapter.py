from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from src.connectors.base import LLMBackend

_T_co = TypeVar("_T_co")

from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.failover_models import FailoverRoute
from src.core.domain.model_utils import ModelDefaults
from src.core.domain.session import Session
from src.core.domain.state_auditing import StateAccessLogEntry
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)


class SessionStateAdapter(
    IApplicationState, ISecureStateAccess, ISecureStateModification
):
    """Adapter that exposes session state via secure interfaces."""

    def __init__(self, session: Session):
        self._session = session
        self._local_state: dict[str, Any] = {}

    def get_command_prefix(self) -> str | None:
        prefix = None
        try:
            prefix = getattr(self._session.state, "command_prefix_override", None)
        except Exception:
            prefix = None
        if isinstance(prefix, str) and prefix:
            return prefix
        return self._local_state.get("command_prefix")

    def get_api_key_redaction_enabled(self) -> bool:
        return bool(self._local_state.get("api_key_redaction_enabled", False))

    def get_disable_interactive_commands(self) -> bool:
        return bool(self._local_state.get("disable_interactive_commands", False))

    def get_failover_routes(self) -> list[FailoverRoute] | None:
        routes_dict = self._session.state.backend_config.failover_routes
        if routes_dict:
            return [
                FailoverRoute(name=name, **(data if isinstance(data, dict) else data.model_dump())) for name, data in routes_dict.items()
            ]
        return None

    def get_access_log(self) -> list[StateAccessLogEntry]:
        """Get the access log for auditing."""
        return []

    def set_command_prefix(self, prefix: str) -> None:
        self._local_state["command_prefix"] = prefix
        with contextlib.suppress(Exception):
            self._session.state = self._session.state.with_command_prefix_override(
                prefix
            )

    def set_api_key_redaction_enabled(self, enabled: bool) -> None:
        self._local_state["api_key_redaction_enabled"] = enabled

    def set_default_api_key_redaction_enabled(self, enabled: bool) -> None:
        """Set the default for whether API key redaction is enabled."""
        self._local_state["default_api_key_redaction_enabled"] = enabled

    def set_disable_interactive_commands(self, disabled: bool) -> None:
        self._local_state["disable_interactive_commands"] = disabled

    def set_failover_routes(self, routes: list[FailoverRoute]) -> None:
        current_backend_config = cast(
            BackendConfiguration, self._session.state.backend_config
        )
        new_backend_config = current_backend_config
        for route in routes:
            if isinstance(route, dict):
                if "name" in route and "policy" in route:
                    name = route["name"]
                    policy = route["policy"]
                    new_backend_config = cast(
                        BackendConfiguration,
                        new_backend_config.with_failover_route(name, policy),
                    )
                    elements = route.get("elements", [])
                    if isinstance(elements, list):
                        for element in elements:
                            new_backend_config = cast(
                                BackendConfiguration,
                                new_backend_config.with_appended_route_element(
                                    name, element
                                ),
                            )
                continue

            name = route.name
            policy = route.policy
            new_backend_config = cast(
                BackendConfiguration,
                new_backend_config.with_failover_route(name, policy),
            )
            elements = route.elements
            if isinstance(elements, list):
                for element in elements:
                    new_backend_config = cast(
                        BackendConfiguration,
                        new_backend_config.with_appended_route_element(name, element),
                    )

        self._session.state = self._session.state.with_backend_config(new_backend_config)

    def get_disable_commands(self) -> bool:
        return bool(self._local_state.get("disable_commands", False))

    def set_disable_commands(self, disabled: bool) -> None:
        self._local_state["disable_commands"] = disabled

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._local_state.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._local_state[key] = value

    def get_use_failover_strategy(self) -> bool:
        return bool(self._local_state.get("PROXY_USE_FAILOVER_STRATEGY", False))

    def set_use_failover_strategy(self, enabled: bool) -> None:
        self._local_state["PROXY_USE_FAILOVER_STRATEGY"] = enabled

    def get_use_streaming_pipeline(self) -> bool:
        return bool(self._local_state.get("PROXY_USE_STREAMING_PIPELINE", False))

    def set_use_streaming_pipeline(self, enabled: bool) -> None:
        self._local_state["PROXY_USE_STREAMING_PIPELINE"] = enabled

    def get_functional_backends(self) -> list[str]:
        val = self._local_state.get("functional_backends", [])
        return val if isinstance(val, list) else []

    def set_functional_backends(self, backends: list[str]) -> None:
        self._local_state["functional_backends"] = backends

    def get_backend_type(self) -> str | None:
        bt = self._local_state.get("backend_type")
        return bt if isinstance(bt, str) else None

    def set_backend_type(self, backend_type: str | None) -> None:
        self._local_state["backend_type"] = backend_type

    def get_backend(self) -> LLMBackend | None:
        return cast("LLMBackend | None", self._local_state.get("backend"))

    def set_backend(self, backend: LLMBackend | None) -> None:
        self._local_state["backend"] = backend

    def get_model_defaults(self) -> dict[str, ModelDefaults]:
        md = self._local_state.get("model_defaults", {})
        return cast(dict[str, ModelDefaults], md if isinstance(md, dict) else {})

    def set_model_defaults(self, defaults: dict[str, ModelDefaults]) -> None:
        self._local_state["model_defaults"] = defaults

    def get_service(self, service_type: type[_T_co]) -> _T_co | None:
        """Session-bound state does not expose DI services."""
        provider = self._local_state.get("service_provider")
        getter = getattr(provider, "get_service", None) if provider else None
        if getter is None or not callable(getter):
            return None
        try:
            return cast(_T_co | None, getter(service_type))
        except Exception:
            return None

    def set_failover_route(self, name: str, route_config: dict[str, Any]) -> None:
        current_backend_config = cast(
            BackendConfiguration, self._session.state.backend_config
        )

        routes_dict: dict[str, Any] = (
            current_backend_config.failover_routes.copy()
            if current_backend_config.failover_routes
            else {}
        )
        routes_dict[name] = route_config

        new_backend_config = current_backend_config.with_failover_route(
            name, route_config.get("policy", "k")
        )
        if "elements" in route_config and isinstance(route_config["elements"], list):
            for element in route_config["elements"]:
                new_backend_config = new_backend_config.with_appended_route_element(
                    name, element
                )
        self._session.state = self._session.state.with_backend_config(
            new_backend_config
        )

    def update_command_prefix(self, prefix: str) -> None:
        """Update command prefix with validation."""
        self.set_command_prefix(prefix)

    def update_api_key_redaction(self, enabled: bool) -> None:
        """Update API key redaction with validation."""
        self.set_api_key_redaction_enabled(enabled)

    def update_interactive_commands(self, disabled: bool) -> None:
        """Update interactive commands setting with validation."""
        self.set_disable_interactive_commands(disabled)

    def update_failover_routes(self, routes: list[FailoverRoute]) -> None:
        """Update failover routes with validation."""
        self.set_failover_routes(routes)
