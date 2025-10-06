"""
Failover commands implementation.

This module provides commands for managing failover routes.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.secure_base_command import StatefulCommandBase
from src.core.domain.session import Session
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)

logger = logging.getLogger(__name__)


class CreateFailoverRouteCommand(StatefulCommandBase):
    """Command to create a new failover route."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "create-failover-route"

    @property
    def format(self) -> str:
        return "create-failover-route(name=<n>,policy=k|m|km|mk)"

    @property
    def description(self) -> str:
        return "Create a new failover route with given policy"

    @property
    def examples(self) -> list[str]:
        return ["!/create-failover-route(name=myroute,policy=k)"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,  # Changed to session: Session
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the create-failover-route command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        name = args.get("name")
        policy = str(args.get("policy", "")).lower()

        if not name or policy not in {"k", "m", "km", "mk"}:
            return CommandResult(
                name=self.name,
                success=False,
                message="create-failover-route requires name and valid policy",
            )

        # Update the session state with the new failover route
        new_backend_config = session.state.backend_config.with_failover_route(  # Changed session_state to session.state
            name, policy
        )
        # Refactored state update
        session.state = session.state.with_backend_config(
            new_backend_config
        )  # Changed session_state._state to session.state

        return CommandResult(
            name=self.name,
            success=True,
            message=f"Failover route '{name}' created with policy '{policy}'",
        )


class DeleteFailoverRouteCommand(StatefulCommandBase):
    """Command to delete a failover route."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "delete-failover-route"

    @property
    def format(self) -> str:
        return "delete-failover-route(name=<route_name>)"

    @property
    def description(self) -> str:
        return "Delete an existing failover route"

    @property
    def examples(self) -> list[str]:
        return ["!/delete-failover-route(name=myroute)"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,  # Changed to session: Session
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the delete-failover-route command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        name = args.get("name")

        if not name:
            return CommandResult(
                name=self.name,
                success=False,
                message="Delete failover route requires name parameter",
            )

        # Check if route exists
        if (
            name not in session.state.backend_config.failover_routes
        ):  # Changed session_state to session.state
            return CommandResult(
                name=self.name,
                success=False,
                message=f"Failover route '{name}' does not exist",
            )

        # Update the session state without the failover route
        new_backend_config = session.state.backend_config.without_failover_route(
            name
        )  # Changed session_state to session.state
        session.state = session.state.with_backend_config(
            new_backend_config
        )  # Changed session_state._state to session.state

        return CommandResult(
            name=self.name, success=True, message=f"Failover route '{name}' deleted"
        )


class ListFailoverRoutesCommand(StatefulCommandBase):
    """Command to list all failover routes."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "list-failover-routes"

    @property
    def format(self) -> str:
        return "list-failover-routes"

    @property
    def description(self) -> str:
        return "List all configured failover routes"

    @property
    def examples(self) -> list[str]:
        return ["!/list-failover-routes"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,  # Changed to session: Session
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the list-failover-routes command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        routes = (
            session.state.backend_config.failover_routes
        )  # Changed session_state to session.state

        if not routes:
            return CommandResult(
                name=self.name, success=True, message="No failover routes defined"
            )

        route_info = []
        for name, route in routes.items():
            policy = route.get("policy", "k")
            route_info.append(f"{name}:{policy}")

        message = "Failover routes: " + ", ".join(route_info)

        return CommandResult(name=self.name, success=True, message=message)


class RouteListCommand(StatefulCommandBase):
    """Command to list route details."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "route-list"

    @property
    def format(self) -> str:
        return "route-list(name=<route_name>)"

    @property
    def description(self) -> str:
        return "List elements in a failover route"

    @property
    def examples(self) -> list[str]:
        return ["!/route-list(name=myroute)"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,  # Changed to session: Session
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the route-list command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        name = args.get("name")

        if not name:
            return CommandResult(
                name=self.name,
                success=False,
                message="Route list requires name parameter",
            )

        # Check if route exists
        if (
            name not in session.state.backend_config.failover_routes
        ):  # Changed session_state to session.state
            return CommandResult(
                name=self.name,
                success=False,
                message=f"Failover route '{name}' does not exist",
            )

        # Get route elements
        elements = session.state.backend_config.get_route_elements(
            name
        )  # Changed session_state to session.state
        route_info = session.state.backend_config.failover_routes[
            name
        ]  # Changed session_state to session.state
        policy = route_info.get("policy", "k")

        if not elements:
            message = f"Failover route '{name}' (policy: {policy}) has no elements"
        else:
            elements_str = ", ".join(elements)
            message = (
                f"Failover route '{name}' (policy: {policy}) elements: {elements_str}"
            )

        return CommandResult(name=self.name, success=True, message=message)


class RouteAppendCommand(StatefulCommandBase):
    """Command to append to a route."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "route-append"

    @property
    def format(self) -> str:
        return "route-append(name=<route_name>,element=<backend:model>)"

    @property
    def description(self) -> str:
        return "Append an element to a failover route"

    @property
    def examples(self) -> list[str]:
        return ["!/route-append(name=myroute,element=openai:gpt-4)"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,  # Changed to session: Session
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the route-append command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        name = args.get("name")
        element = args.get("element")

        if not name or not element:
            return CommandResult(
                name=self.name,
                success=False,
                message="Route append requires name and element parameters",
            )

        # Check if route exists
        if (
            name not in session.state.backend_config.failover_routes
        ):  # Changed session_state to session.state
            return CommandResult(
                name=self.name,
                success=False,
                message=f"Failover route '{name}' does not exist",
            )

        # Validate element format (backend:model or model)
        if ":" in element:
            backend, _model = element.split(":", 1)
            # context.backend_factory may be a Mock in tests; handle gracefully
            backend_types = None
            try:
                backend_types = getattr(context.backend_factory, "_backend_types", None)
            except Exception:
                backend_types = None

            if backend_types is not None:
                # backend_types may be a Mock in tests; attempt to extract iterable keys
                try:
                    if isinstance(backend_types, dict) or (
                        hasattr(backend_types, "keys") and callable(backend_types.keys)
                    ):
                        keys = list(backend_types.keys())
                    else:
                        # Try to iterate over it
                        keys = list(backend_types)
                except Exception:
                    keys = []
                if keys and backend not in keys:
                    return CommandResult(
                        name=self.name,
                        success=False,
                        message=f"Backend '{backend}' in element '{element}' is not supported",
                    )

        # Update the session state with the appended element
        new_backend_config = session.state.backend_config.with_appended_route_element(
            name, element
        )
        session.state = session.state.with_backend_config(new_backend_config)

        return CommandResult(
            name=self.name,
            success=True,
            message=f"Element '{element}' appended to failover route '{name}'",
        )


class RoutePrependCommand(StatefulCommandBase):
    """Command to prepend to a route."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "route-prepend"

    @property
    def format(self) -> str:
        return "route-prepend(name=<route_name>,element=<backend:model>)"

    @property
    def description(self) -> str:
        return "Prepend an element to a failover route"

    @property
    def examples(self) -> list[str]:
        return ["!/route-prepend(name=myroute,element=openai:gpt-4)"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,  # Changed to session: Session
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the route-prepend command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        name = args.get("name")
        element = args.get("element")

        if not name or not element:
            return CommandResult(
                name=self.name,
                success=False,
                message="Route prepend requires name and element parameters",
            )

        # Check if route exists
        if (
            name not in session.state.backend_config.failover_routes
        ):  # Changed session_state to session.state
            return CommandResult(
                name=self.name,
                success=False,
                message=f"Failover route '{name}' does not exist",
            )

        # Validate element format (backend:model or model)
        if ":" in element:
            backend, _model = element.split(":", 1)
            if context and backend not in context.backend_factory._backend_types:
                return CommandResult(
                    name=self.name,
                    success=False,
                    message=f"Backend '{backend}' in element '{element}' is not supported",
                )

        # Update the session state with the prepended element
        new_backend_config = session.state.backend_config.with_prepended_route_element(  # Changed session_state to session.state
            name, element
        )
        session.state = session.state.with_backend_config(
            new_backend_config
        )  # Changed session_state._state to session.state

        return CommandResult(
            name=self.name,
            success=True,
            message=f"Element '{element}' prepended to failover route '{name}'",
        )


class RouteClearCommand(StatefulCommandBase):
    """Command to clear a route."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "route-clear"

    @property
    def format(self) -> str:
        return "route-clear(name=<route_name>)"

    @property
    def description(self) -> str:
        return "Clear all elements from a failover route"

    @property
    def examples(self) -> list[str]:
        return ["!/route-clear(name=myroute)"]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,  # Changed to session: Session
        context: Any = None,
    ) -> CommandResult:
        """
        Execute the route-clear command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        name = args.get("name")

        if not name:
            return CommandResult(
                name=self.name,
                success=False,
                message="Route clear requires name parameter",
            )

        # Check if route exists
        if (
            name not in session.state.backend_config.failover_routes
        ):  # Changed session_state to session.state
            return CommandResult(
                name=self.name,
                success=False,
                message=f"Failover route '{name}' does not exist",
            )

        # Update the session state with the cleared route
        new_backend_config = session.state.backend_config.with_cleared_route(
            name
        )  # Changed session_state to session.state
        session.state = session.state.with_backend_config(
            new_backend_config
        )  # Changed session_state._state to session.state

        return CommandResult(
            name=self.name,
            success=True,
            message=f"All elements cleared from failover route '{name}'",
        )


# Register all failover commands in the global registry
from src.core.domain.commands.command_registry import domain_command_registry

domain_command_registry.register_command(
    "create-failover-route", CreateFailoverRouteCommand
)
domain_command_registry.register_command(
    "delete-failover-route", DeleteFailoverRouteCommand
)
domain_command_registry.register_command(
    "list-failover-routes", ListFailoverRoutesCommand
)
domain_command_registry.register_command("route-append", RouteAppendCommand)
domain_command_registry.register_command("route-clear", RouteClearCommand)
domain_command_registry.register_command("route-list", RouteListCommand)
domain_command_registry.register_command("route-prepend", RoutePrependCommand)
