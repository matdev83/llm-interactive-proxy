from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionStateAdapter
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class CreateFailoverRouteHandler(BaseCommandHandler):
    """Handler for creating a new failover route."""

    def __init__(self) -> None:
        """Initialize the create failover route handler."""
        super().__init__("create-failover-route")

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Create a new failover route with given policy"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/create-failover-route(name=myroute,policy=k)"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name == self.name

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle creating a failover route.

        Args:
            param_value: Dictionary with name and policy
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not isinstance(param_value, dict):
            return CommandHandlerResult(
                success=False,
                message="Create failover route requires name and policy parameters",
            )

        name = param_value.get("name")
        policy = str(param_value.get("policy", "")).lower()

        if not name or policy not in {"k", "m", "km", "mk"}:
            return CommandHandlerResult(
                success=False,
                message="Create failover route requires name and valid policy (k, m, km, or mk)",
            )

        # Create new state with failover route
        builder = SessionStateBuilder(current_state)
        new_state = SessionStateAdapter(
            builder.with_backend_config(
                current_state.backend_config.with_failover_route(name, policy)
            ).build()
        )

        return CommandHandlerResult(
            success=True,
            message=f"Failover route '{name}' created with policy '{policy}'",
            new_state=new_state,
        )


class DeleteFailoverRouteHandler(BaseCommandHandler):
    """Handler for deleting a failover route."""

    def __init__(self) -> None:
        """Initialize the delete failover route handler."""
        super().__init__("delete-failover-route")

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Delete an existing failover route"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/delete-failover-route(name=myroute)"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name == self.name

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle deleting a failover route.

        Args:
            param_value: Dictionary with name
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not isinstance(param_value, dict):
            return CommandHandlerResult(
                success=False, message="Delete failover route requires name parameter"
            )

        name = param_value.get("name")

        if not name:
            return CommandHandlerResult(
                success=False, message="Delete failover route requires name parameter"
            )

        # Check if route exists
        if name not in current_state.backend_config.failover_routes:
            return CommandHandlerResult(
                success=False, message=f"Failover route '{name}' does not exist"
            )

        # Create new state without failover route
        builder = SessionStateBuilder(current_state)
        new_state = SessionStateAdapter(
            builder.with_backend_config(
                current_state.backend_config.without_failover_route(name)
            ).build()
        )

        return CommandHandlerResult(
            success=True,
            message=f"Failover route '{name}' deleted",
            new_state=new_state,
        )


class RouteListHandler(BaseCommandHandler):
    """Handler for listing failover routes."""

    def __init__(self) -> None:
        """Initialize the route list handler."""
        super().__init__("route-list")

    @property
    def description(self) -> str:
        """Description of the command."""
        return "List elements in a failover route"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/route-list(name=myroute)"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name == self.name

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle listing elements in a failover route.

        Args:
            param_value: Dictionary with name
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status
        """
        if not isinstance(param_value, dict):
            return CommandHandlerResult(
                success=False, message="Route list requires name parameter"
            )

        name = param_value.get("name")

        if not name:
            return CommandHandlerResult(
                success=False, message="Route list requires name parameter"
            )

        # Check if route exists
        if name not in current_state.backend_config.failover_routes:
            return CommandHandlerResult(
                success=False, message=f"Failover route '{name}' does not exist"
            )

        # Get route elements
        elements = current_state.backend_config.get_route_elements(name)
        route_info = current_state.backend_config.failover_routes[name]
        policy = route_info.get("policy", "k")

        if not elements:
            message = f"Failover route '{name}' (policy: {policy}) has no elements"
        else:
            elements_str = ", ".join(elements)
            message = (
                f"Failover route '{name}' (policy: {policy}) elements: {elements_str}"
            )

        return CommandHandlerResult(success=True, message=message)


class RouteAppendHandler(BaseCommandHandler):
    """Handler for appending elements to a failover route."""

    def __init__(self) -> None:
        """Initialize the append route handler."""
        super().__init__("route-append")

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Append an element to a failover route"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/route-append(name=myroute,element=openai:gpt-4)"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name == self.name

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle appending an element to a failover route.

        Args:
            param_value: Dictionary with name and element
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not isinstance(param_value, dict):
            return CommandHandlerResult(
                success=False,
                message="Route append requires name and element parameters",
            )

        name = param_value.get("name")
        element = param_value.get("element")

        if not name or not element:
            return CommandHandlerResult(
                success=False,
                message="Route append requires name and element parameters",
            )

        # Check if route exists
        if name not in current_state.backend_config.failover_routes:
            return CommandHandlerResult(
                success=False, message=f"Failover route '{name}' does not exist"
            )

        # Validate element format (backend:model or model)
        if ":" in element:
            backend, model = element.split(":", 1)
            from src.core.services.backend_registry_service import backend_registry # Added this import
            if (
                context
                and backend
                not in backend_registry.get_registered_backends()
            ):
                return CommandHandlerResult(
                    success=False,
                    message=f"Backend '{backend}' in element '{element}' is not supported",
                )

        # Create new state with appended element
        builder = SessionStateBuilder(current_state)
        new_state = SessionStateAdapter(
            builder.with_backend_config(
                current_state.backend_config.with_appended_route_element(name, element)
            ).build()
        )

        return CommandHandlerResult(
            success=True,
            message=f"Element '{element}' appended to failover route '{name}'",
            new_state=new_state,
        )


class RoutePrependHandler(BaseCommandHandler):
    """Handler for prepending elements to a failover route."""

    def __init__(self) -> None:
        """Initialize the prepend route handler."""
        super().__init__("route-prepend")

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Prepend an element to a failover route"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/route-prepend(name=myroute,element=openai:gpt-4)"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name == self.name

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle prepending an element to a failover route.

        Args:
            param_value: Dictionary with name and element
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not isinstance(param_value, dict):
            return CommandHandlerResult(
                success=False,
                message="Route prepend requires name and element parameters",
            )

        name = param_value.get("name")
        element = param_value.get("element")

        if not name or not element:
            return CommandHandlerResult(
                success=False,
                message="Route prepend requires name and element parameters",
            )

        # Check if route exists
        if name not in current_state.backend_config.failover_routes:
            return CommandHandlerResult(
                success=False, message=f"Failover route '{name}' does not exist"
            )

        # Validate element format (backend:model or model)
        if ":" in element:
            backend, model = element.split(":", 1)
            if (
                context
                and backend
                not in context.backend_factory._backend_registry.get_registered_backends()
            ):
                return CommandHandlerResult(
                    success=False,
                    message=f"Backend '{backend}' in element '{element}' is not supported",
                )

        # Create new state with prepended element
        builder = SessionStateBuilder(current_state)
        new_state = SessionStateAdapter(
            builder.with_backend_config(
                current_state.backend_config.with_prepended_route_element(name, element)
            ).build()
        )

        return CommandHandlerResult(
            success=True,
            message=f"Element '{element}' prepended to failover route '{name}'",
            new_state=new_state,
        )


class RouteClearHandler(BaseCommandHandler):
    """Handler for clearing elements from a failover route."""

    def __init__(self) -> None:
        """Initialize the clear route handler."""
        super().__init__("route-clear")

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Clear all elements from a failover route"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/route-clear(name=myroute)"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name == self.name

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle clearing elements from a failover route.

        Args:
            param_value: Dictionary with name
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not isinstance(param_value, dict):
            return CommandHandlerResult(
                success=False, message="Route clear requires name parameter"
            )

        name = param_value.get("name")

        if not name:
            return CommandHandlerResult(
                success=False, message="Route clear requires name parameter"
            )

        # Check if route exists
        if name not in current_state.backend_config.failover_routes:
            return CommandHandlerResult(
                success=False, message=f"Failover route '{name}' does not exist"
            )

        # Create new state with cleared route
        builder = SessionStateBuilder(current_state)
        new_state = SessionStateAdapter(
            builder.with_backend_config(
                current_state.backend_config.with_cleared_route(name)
            ).build()
        )

        return CommandHandlerResult(
            success=True,
            message=f"All elements cleared from failover route '{name}'",
            new_state=new_state,
        )


class ListFailoverRoutesHandler(BaseCommandHandler):
    """Handler for listing all failover routes."""

    def __init__(self) -> None:
        """Initialize the list failover routes handler."""
        super().__init__("list-failover-routes")

    @property
    def description(self) -> str:
        """Description of the command."""
        return "List all configured failover routes"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/list-failover-routes"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name == self.name

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle listing all failover routes.

        Args:
            param_value: Not used
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status
        """
        routes = current_state.backend_config.failover_routes

        if not routes:
            return CommandHandlerResult(
                success=True, message="No failover routes defined"
            )

        route_info = []
        for name, route in routes.items():
            policy = route.get("policy", "k")
            route_info.append(f"{name}:{policy}")

        message = "Failover routes: " + ", ".join(route_info)

        return CommandHandlerResult(success=True, message=message)
