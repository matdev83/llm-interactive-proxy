"""
A command handler for the failover commands.
"""

from typing import TYPE_CHECKING, Any, cast

from src.core.commands.command import Command, CommandResult
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
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
from src.core.domain.session import Session
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


class SessionStateApplicationStateAdapter(
    IApplicationState, ISecureStateAccess, ISecureStateModification
):
    def __init__(self, session: Session):
        self._session = session

    def get_command_prefix(self) -> str | None:
        return None

    def get_api_key_redaction_enabled(self) -> bool:
        return False

    def get_disable_interactive_commands(self) -> bool:
        return False

    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        routes_dict = self._session.state.backend_config.failover_routes
        if routes_dict:
            return [{"name": name, **data} for name, data in routes_dict.items()]
        return None

    def set_command_prefix(self, prefix: str) -> None:
        pass

    def set_api_key_redaction_enabled(self, enabled: bool) -> None:
        pass

    def set_disable_interactive_commands(self, disabled: bool) -> None:
        pass

    def set_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        # Start with a clean backend config
        current_backend_config = cast(
            BackendConfiguration, self._session.state.backend_config
        )
        new_backend_config = current_backend_config
        # Add each route one by one
        for route in routes:
            if "name" in route and "policy" in route:
                name = route["name"]
                policy = route["policy"]
                # Create a new config with this route
                new_backend_config = cast(
                    BackendConfiguration,
                    new_backend_config.with_failover_route(name, policy),
                )

                # If the route has elements, we need to add them
                if "elements" in route:
                    elements = route["elements"]
                    if isinstance(elements, list):
                        for element in elements:
                            new_backend_config = cast(
                                BackendConfiguration,
                                new_backend_config.with_appended_route_element(
                                    name, element
                                ),
                            )

        self._session.state = self._session.state.with_backend_config(
            new_backend_config
        )

    def get_disable_commands(self) -> bool:
        return False

    def set_disable_commands(self, disabled: bool) -> None:
        pass

    def get_setting(self, key: str, default: Any = None) -> Any:
        return default

    def set_setting(self, key: str, value: Any) -> None:
        pass

    def get_use_failover_strategy(self) -> bool:
        return False

    def set_use_failover_strategy(self, enabled: bool) -> None:
        pass

    def get_use_streaming_pipeline(self) -> bool:
        return False

    def set_use_streaming_pipeline(self, enabled: bool) -> None:
        pass

    def get_functional_backends(self) -> list[str]:
        return []

    def set_functional_backends(self, backends: list[str]) -> None:
        pass

    def get_backend_type(self) -> str | None:
        return None

    def set_backend_type(self, backend_type: str | None) -> None:
        pass

    def get_backend(self) -> Any:
        return None

    def set_backend(self, backend: Any) -> None:
        pass

    def get_model_defaults(self) -> dict[str, Any]:
        return {}

    def set_model_defaults(self, defaults: dict[str, Any]) -> None:
        pass

    def set_failover_route(self, name: str, route_config: dict[str, Any]) -> None:
        current_backend_config = cast(
            BackendConfiguration, self._session.state.backend_config
        )

        routes_dict = (
            current_backend_config.failover_routes.copy()
            if current_backend_config.failover_routes
            else {}
        )
        routes_dict[name] = route_config

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

    def update_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        """Update failover routes with validation."""
        self.set_failover_routes(routes)


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
        command_service: "ICommandService | None" = None,
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
