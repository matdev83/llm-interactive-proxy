"""
A command handler for failover commands.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import TYPE_CHECKING, Any, TypeVar, cast

from src.core.commands.handler import ICommandHandler
from src.core.commands.models import Command
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.failover_commands import (
    CreateFailoverRouteCommand,
    DeleteFailoverRouteCommand,
    ListFailoverRoutesCommand,
    RouteAppendCommand,
    RouteClearCommand,
    RouteListCommand,
    RoutePrependCommand,
)
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.failover_models import FailoverRoute
from src.core.domain.model_utils import ModelDefaults
from src.core.domain.session import Session
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)

if TYPE_CHECKING:
    from src.connectors.base import LLMBackend
    from src.core.domain.state_auditing import StateAccessLogEntry
    from src.core.interfaces.command_service_interface import ICommandService

_T_co = TypeVar("_T_co")


class SessionStateApplicationStateAdapter(
    IApplicationState, ISecureStateAccess, ISecureStateModification
):
    def __init__(self, session: Session):
        self._session = session
        self._local_state: dict[str, Any] = {}
        self._lock = threading.Lock()

    def get_command_prefix(self) -> str | None:
        logger = logging.getLogger(__name__)
        prefix = None
        try:
            prefix = getattr(self._session.state, "command_prefix_override", None)
        except Exception:
            logger.warning(
                "Failed to get command prefix from session state",
                exc_info=True,
            )
            prefix = None
        if isinstance(prefix, str) and prefix:
            return prefix
        with self._lock:
            return self._local_state.get("command_prefix")

    def get_api_key_redaction_enabled(self) -> bool:
        with self._lock:
            return bool(self._local_state.get("api_key_redaction_enabled", False))

    def get_disable_interactive_commands(self) -> bool:
        with self._lock:
            return bool(self._local_state.get("disable_interactive_commands", False))

    def get_failover_routes(self) -> list[FailoverRoute] | None:
        routes_dict = self._session.state.backend_config.failover_routes
        if routes_dict:
            routes: list[FailoverRoute] = []
            for name, data in routes_dict.items():
                if isinstance(data, FailoverRoute):
                    routes.append(data)
                elif isinstance(data, dict):
                    routes.append(FailoverRoute(name=name, **data))
                elif hasattr(data, "model_dump"):
                    routes.append(FailoverRoute(name=name, **data.model_dump()))
            return routes
        return None

    def get_access_log(self) -> list[StateAccessLogEntry]:
        return []

    def set_command_prefix(self, prefix: str) -> None:
        with self._lock:
            self._local_state["command_prefix"] = prefix
        with contextlib.suppress(Exception):
            self._session.state = self._session.state.with_command_prefix_override(
                prefix
            )

    def set_api_key_redaction_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._local_state["api_key_redaction_enabled"] = enabled

    def set_default_api_key_redaction_enabled(self, enabled: bool) -> None:
        """Set default for whether API key redaction is enabled."""
        with self._lock:
            self._local_state["default_api_key_redaction_enabled"] = enabled

    def set_disable_interactive_commands(self, disabled: bool) -> None:
        with self._lock:
            self._local_state["disable_interactive_commands"] = disabled

    def get_disable_commands(self) -> bool:
        with self._lock:
            return bool(self._local_state.get("disable_commands", False))

    def set_disable_commands(self, disabled: bool) -> None:
        with self._lock:
            self._local_state["disable_commands"] = disabled

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._local_state.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._local_state[key] = value

    def get_use_failover_strategy(self) -> bool:
        with self._lock:
            return bool(self._local_state.get("PROXY_USE_FAILOVER_STRATEGY", False))

    def set_use_failover_strategy(self, enabled: bool) -> None:
        with self._lock:
            self._local_state["PROXY_USE_FAILOVER_STRATEGY"] = enabled

    def get_use_streaming_pipeline(self) -> bool:
        with self._lock:
            return bool(self._local_state.get("PROXY_USE_STREAMING_PIPELINE", False))

    def set_use_streaming_pipeline(self, enabled: bool) -> None:
        with self._lock:
            self._local_state["PROXY_USE_STREAMING_PIPELINE"] = enabled

    def get_functional_backends(self) -> list[str]:
        with self._lock:
            val = self._local_state.get("functional_backends", [])
            return val if isinstance(val, list) else []

    def set_functional_backends(self, backends: list[str]) -> None:
        with self._lock:
            self._local_state["functional_backends"] = backends

    def get_backend_type(self) -> str | None:
        with self._lock:
            bt = self._local_state.get("backend_type")
            return bt if isinstance(bt, str) else None

    def set_backend_type(self, backend_type: str | None) -> None:
        with self._lock:
            self._local_state["backend_type"] = backend_type

    def get_backend(self) -> LLMBackend | None:
        with self._lock:
            return cast("LLMBackend | None", self._local_state.get("backend"))

    def set_backend(self, backend: LLMBackend | None) -> None:
        with self._lock:
            self._local_state["backend"] = backend

    def get_model_defaults(self) -> dict[str, ModelDefaults]:
        with self._lock:
            md = self._local_state.get("model_defaults", {})
            return cast(dict[str, ModelDefaults], md if isinstance(md, dict) else {})

    def set_model_defaults(self, defaults: dict[str, ModelDefaults]) -> None:
        with self._lock:
            self._local_state["model_defaults"] = defaults

    def get_service(self, service_type: type[_T_co]) -> _T_co | None:
        logger = logging.getLogger(__name__)
        with self._lock:
            provider = self._local_state.get("service_provider")
            getter = getattr(provider, "get_service", None) if provider else None
        if getter is None or not callable(getter):
            return None
        try:
            return cast(_T_co | None, getter(service_type))
        except Exception:
            logger.warning(
                "Failed to get service %s from provider",
                getattr(service_type, "__name__", repr(service_type)),
                exc_info=True,
            )
            return None

    def set_failover_route(self, name: str, route_config: dict[str, Any]) -> None:
        current_backend_config = cast(
            BackendConfiguration, self._session.state.backend_config
        )

        new_backend_config = current_backend_config.with_failover_route(
            name, route_config.get("policy", "k")
        )
        # Add elements if they exist
        if "elements" in route_config and isinstance(route_config["elements"], list):
            for element in route_config["elements"]:
                new_backend_config = new_backend_config.with_appended_route_element(
                    name, element
                )
        self._session.state = self._session.state.with_backend_config(
            new_backend_config
        )

    # Implement methods required by ISecureStateModification
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

    def set_failover_routes(self, routes: list[FailoverRoute]) -> None:
        """Set multiple failover routes."""
        with self._lock:
            self._local_state["failover_routes"] = {}
            for route in routes:
                if isinstance(route, dict):
                    if "name" in route:
                        name = route["name"]
                        route_config = {k: v for k, v in route.items() if k != "name"}
                        self._local_state["failover_routes"][name] = route_config
                    continue

                name = route.name
                route_config = route.model_dump(exclude={"name"})
                self._local_state["failover_routes"][name] = route_config


@command("create-failover-route")
@command("delete-failover-route")
@command("list-failover-routes")
@command("route-append")
@command("route-clear")
@command("route-list")
@command("route-prepend")
class FailoverCommandHandler(ICommandHandler):
    """
    A command handler for the failover commands.
    """

    def __init__(
        self,
        command_service: ICommandService | None = None,
        secure_state_access: Any | None = None,
        secure_state_modification: Any | None = None,
    ) -> None:
        super().__init__(
            command_service,
            secure_state_access=secure_state_access,
            secure_state_modification=secure_state_modification,
        )

    @property
    def command_name(self) -> str:
        """Get the command name."""
        return "failover"

    @property
    def description(self) -> str:
        """Get the command description."""
        return "Manage failover routes."

    @property
    def format(self) -> str:
        """Get the command format."""
        return "failover"

    @property
    def examples(self) -> list[str]:
        """Get command usage examples."""
        return [
            "create-failover-route(name=myroute,policy=k)",
            "delete-failover-route(name=myroute)",
            "list-failover-routes",
            "route-append(name=myroute,element=openai:gpt-4)",
            "route-clear(name=myroute)",
            "route-list(name=myroute)",
            "route-prepend(name=myroute,element=openai:gpt-4)",
        ]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle the failover command."""
        # Map command names to their corresponding classes
        command_map = {
            "create-failover-route": CreateFailoverRouteCommand,
            "delete-failover-route": DeleteFailoverRouteCommand,
            "list-failover-routes": ListFailoverRoutesCommand,
            "route-append": RouteAppendCommand,
            "route-clear": RouteClearCommand,
            "route-list": RouteListCommand,
            "route-prepend": RoutePrependCommand,
        }

        # Get the appropriate command class
        # Get the appropriate command class
        command_class_raw = command_map.get(command.name)
        if not command_class_raw:
            return CommandResult(
                success=False, message=f"Unknown failover command: {command.name}"
            )

        # Ensure the command class is treated as a concrete type for instantiation
        from src.core.domain.commands.secure_base_command import (
            StatefulCommandBase,
            create_secure_command,
        )

        command_class = cast(type[StatefulCommandBase], command_class_raw)

        # Prefer injected secure state services if available, else adapt the session
        state_reader = (
            self._secure_state_access
            if isinstance(self._secure_state_access, ISecureStateAccess)
            else SessionStateApplicationStateAdapter(session)
        )
        if isinstance(self._secure_state_modification, ISecureStateModification):
            state_modifier: ISecureStateModification | None = (
                self._secure_state_modification
            )
        else:
            # SessionStateApplicationStateAdapter implements both access and modification
            state_modifier = state_reader  # type: ignore[assignment]

        failover_command = create_secure_command(
            command_class, state_reader=state_reader, state_modifier=state_modifier
        )

        # Execute the command
        result = await failover_command.execute(command.args, session)

        return CommandResult(
            success=result.success,
            message=result.message,
            new_state=session.state,
        )
