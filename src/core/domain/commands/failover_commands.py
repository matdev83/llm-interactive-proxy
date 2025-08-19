"""
Failover commands implementation.

This module provides commands for managing failover routes.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session  # Added Session import

logger = logging.getLogger(__name__)


class CreateFailoverRouteCommand(BaseCommand):
    """Command to create a new failover route."""

    name = "create-failover-route"
    format = "create-failover-route(name=<n>,policy=k|m|km|mk)"
    description = "Create a new failover route with given policy"
    examples = ["!/create-failover-route(name=myroute,policy=k)"]

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
        ).with_interactive_just_enabled(
            True
        )  # Changed session_state._state to session.state

        return CommandResult(
            name=self.name,
            success=True,
            message=f"Failover route '{name}' created with policy '{policy}'",
        )


class DeleteFailoverRouteCommand(BaseCommand):
    """Command to delete an existing failover route."""

    name = "delete-failover-route"
    format = "delete-failover-route(name=<route_name>)"
    description = "Delete an existing failover route"
    examples = ["!/delete-failover-route(name=myroute)"]

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


class ListFailoverRoutesCommand(BaseCommand):
    """Command to list all configured failover routes."""

    name = "list-failover-routes"
    format = "list-failover-routes"
    description = "List all configured failover routes"
    examples = ["!/list-failover-routes"]

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


class RouteListCommand(BaseCommand):
    """Command to list elements in a failover route."""

    name = "route-list"
    format = "route-list(name=<route_name>)"
    description = "List elements in a failover route"
    examples = ["!/route-list(name=myroute)"]

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


class RouteAppendCommand(BaseCommand):
    """Command to append an element to a failover route."""

    name = "route-append"
    format = "route-append(name=<route_name>,element=<backend:model>)"
    description = "Append an element to a failover route"
    examples = ["!/route-append(name=myroute,element=openai:gpt-4)"]

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
            backend, model = element.split(":", 1)
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


class RoutePrependCommand(BaseCommand):
    """Command to prepend an element to a failover route."""

    name = "route-prepend"
    format = "route-prepend(name=<route_name>,element=<backend:model>)"
    description = "Prepend an element to a failover route"
    examples = ["!/route-prepend(name=myroute,element=openai:gpt-4)"]

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
            backend, model = element.split(":", 1)
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


class RouteClearCommand(BaseCommand):
    """Command to clear all elements from a failover route."""

    name = "route-clear"
    format = "route-clear(name=<route_name>)"
    description = "Clear all elements from a failover route"
    examples = ["!/route-clear(name=myroute)"]

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
