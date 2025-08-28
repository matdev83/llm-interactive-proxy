"""
Failover service for handling backend failover.

This module provides a service for handling backend failover, which is responsible
for determining the appropriate failover route for a given backend type.
"""

from dataclasses import dataclass
from typing import Any

from src.core.common.logging_utils import get_logger
from src.core.domain.model_utils import parse_model_backend

logger = get_logger(__name__)


from src.core.interfaces.model_bases import InternalDTO


@dataclass
class FailoverAttempt(InternalDTO):
    """Represents a single failover attempt."""

    backend: str
    model: str


class FailoverService:
    """Service for handling backend failover."""

    def __init__(self, failover_routes: dict[str, Any]) -> None:
        """Initialize the failover service.

        Args:
            failover_routes: A dictionary mapping backend types to failover routes
        """
        self.failover_routes: dict[str, Any] = failover_routes or {}
        # Disable debug logging to improve test performance
        # logger.debug(
        #     "Initialized failover service",
        #     failover_routes=self.failover_routes,
        # )

    def get_failover_route(self, backend_type: str) -> Any | None:
        """Get the failover route for a backend type.

        Args:
            backend_type: The backend type to get the failover route for

        Returns:
            The failover route, or None if no failover route is configured
        """
        failover_route = self.failover_routes.get(backend_type)
        if failover_route:
            logger.info(
                "Found failover route",
                backend_type=backend_type,
                failover_route=failover_route,
            )
        else:
            logger.debug("No failover route found", backend_type=backend_type)
        return failover_route

    def get_failover_attempts(
        self, backend_config: Any, model: str, backend_type: str
    ) -> list[FailoverAttempt]:
        """Get the list of failover attempts for a model.

        Args:
            backend_config: The backend configuration
            model: The model name
            backend_type: The backend type

        Returns:
            List of failover attempts
        """
        # Get the route configuration
        route_config = backend_config.failover_routes.get(model)
        if not route_config:
            logger.debug("No failover route found for model", model=model)
            return []

        policy = route_config.get("policy", "k")
        elements = route_config.get("elements", [])

        logger.debug(
            "Getting failover attempts", model=model, policy=policy, elements=elements
        )

        attempts = []
        for element in elements:
            try:
                # Parse the element into backend and model
                elem_backend, elem_model = parse_model_backend(element)
                attempts.append(FailoverAttempt(backend=elem_backend, model=elem_model))
            except ValueError:
                logger.warning(
                    "Failed to parse failover route element",
                    element=element,
                    exc_info=True,
                )
                continue

        return attempts

    def add_failover_route(self, backend_type: str, failover_route: Any) -> None:
        """Add a failover route.

        Args:
            backend_type: The backend type to add a failover route for
            failover_route: The failover route to add
        """
        self.failover_routes[backend_type] = failover_route
        logger.info(
            "Added failover route",
            backend_type=backend_type,
            failover_route=failover_route,
        )

    def remove_failover_route(self, backend_type: str) -> bool:
        """Remove a failover route.

        Args:
            backend_type: The backend type to remove the failover route for

        Returns:
            True if the failover route was removed, False otherwise
        """
        if backend_type in self.failover_routes:
            del self.failover_routes[backend_type]
            logger.info("Removed failover route", backend_type=backend_type)
            return True
        logger.debug("No failover route to remove", backend_type=backend_type)
        return False

    def get_all_failover_routes(self) -> dict[str, Any]:
        """Get all failover routes.

        Returns:
            A dictionary mapping backend types to failover routes
        """
        return dict(self.failover_routes)

    def clear_failover_routes(self) -> None:
        """Clear all failover routes."""
        self.failover_routes.clear()
        logger.info("Cleared all failover routes")
