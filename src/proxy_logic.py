import logging
from typing import Optional, List, Dict # Add Dict import

logger = logging.getLogger(__name__)


class ProxyState:
    """Manages the state of the proxy, particularly model overrides."""

    def __init__(
        self,
        interactive_mode: bool = True,
        failover_routes: Optional[Dict[str, Dict[str, List[str]]]] = None,
    ) -> None:
        self.override_backend: Optional[str] = None
        self.override_model: Optional[str] = None
        self.invalid_override: bool = False
        self.project: Optional[str] = None
        self.interactive_mode: bool = interactive_mode
        self.interactive_just_enabled: bool = False
        self.hello_requested: bool = False
        self.failover_routes: Dict[str, Dict[str, List[str]]] = (
            failover_routes if failover_routes is not None else {}
        )

    def set_override_model(
        self, backend: str, model_name: str, *, invalid: bool = False
    ) -> None:
        logger.debug(
            f"ProxyState.set_override_model called with: backend={backend}, model_name={model_name}, invalid={invalid}"
        )
        self.override_backend = backend
        self.override_model = model_name
        self.invalid_override = invalid

    def set_override_backend(self, backend: str) -> None:
        """Override only the backend to use for this session."""
        logger.info(f"Setting override backend to: {backend} for ProxyState ID: {id(self)}")
        self.override_backend = backend
        self.override_model = None
        self.invalid_override = False

    def unset_override_model(self) -> None:
        logger.info("Unsetting override model.")
        self.override_backend = None
        self.override_model = None
        self.invalid_override = False

    def unset_override_backend(self) -> None:
        """Remove any backend override."""
        logger.info("Unsetting override backend.")
        self.override_backend = None
        self.override_model = None
        self.invalid_override = False

    def set_project(self, project_name: str) -> None:
        logger.info(f"Setting project to: {project_name}")
        self.project = project_name

    def unset_project(self) -> None:
        logger.info("Unsetting project.")
        self.project = None

    def set_interactive_mode(self, value: bool) -> None:
        logger.info(f"Setting interactive mode to: {value}")
        if value and not self.interactive_mode:
            self.interactive_just_enabled = True
        else:
            self.interactive_just_enabled = False
        self.interactive_mode = value

    def unset_interactive_mode(self) -> None:
        logger.info("Unsetting interactive mode (setting to False).")
        self.interactive_mode = False
        self.interactive_just_enabled = False

    # Failover route management -------------------------------------------------
    def create_failover_route(self, name: str, policy: str) -> None:
        self.failover_routes[name] = {"policy": policy, "elements": []}

    def delete_failover_route(self, name: str) -> None:
        self.failover_routes.pop(name, None)

    def clear_route(self, name: str) -> None:
        route = self.failover_routes.get(name)
        if route is not None:
            route["elements"] = []

    def append_route_element(self, name: str, element: str) -> None:
        route = self.failover_routes.setdefault(name, {"policy": "k", "elements": []})
        route.setdefault("elements", []).append(element)

    def prepend_route_element(self, name: str, element: str) -> None:
        route = self.failover_routes.setdefault(name, {"policy": "k", "elements": []})
        route.setdefault("elements", []).insert(0, element)

    def list_routes(self) -> dict[str, str]:
        return {n: r.get("policy", "") for n, r in self.failover_routes.items()}

    def list_route(self, name: str) -> list[str]:
        route = self.failover_routes.get(name)
        if route is None:
            return []
        return list(route.get("elements", []))

    def reset(self) -> None:
        logger.info("Resetting ProxyState instance.")
        self.override_backend = None
        self.override_model = None
        self.invalid_override = False
        self.project = None
        self.interactive_mode = False
        self.interactive_just_enabled = False
        self.hello_requested = False

    def get_effective_model(self, requested_model: str) -> str:
        if self.override_model:
            logger.info(
                f"Overriding requested model '{requested_model}' with '{self.override_model}'"
            )
            return self.override_model
        return requested_model

    def get_selected_backend(self, default_backend: str) -> str:
        return self.override_backend or default_backend


# Re-export command parsing helpers from the dedicated module for backward compatibility
from .command_parser import (
    parse_arguments,
    get_command_pattern,
    _process_text_for_commands,
    process_commands_in_messages,
    CommandParser,
)

__all__ = [
    "ProxyState",
    "parse_arguments",
    "get_command_pattern",
    "_process_text_for_commands",
    "process_commands_in_messages",
    "CommandParser",
]
