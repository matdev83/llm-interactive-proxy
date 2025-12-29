"""
Failover service for handling backend failover.

This module provides a service for handling backend failover, which is responsible
for determining the appropriate failover route for a given backend type.
"""

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import Field, ValidationError, model_validator

from src.core.common.logging_utils import get_logger, is_log_level_enabled
from src.core.domain.model_utils import parse_model_backend
from src.core.interfaces.model_bases import DomainModel, InternalDTO

logger = get_logger(__name__)


class FailoverRouteConfig(DomainModel):
    """Configuration for a failover route."""

    policy: str = "k"
    elements: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def handle_string(cls, data: Any) -> Any:
        """Allow initializing from a string (simple route with one element)."""
        if isinstance(data, str):
            return {"elements": [data]}
        return data

    def __eq__(self, other: Any) -> bool:
        """Support comparison with strings for backward compatibility."""
        if isinstance(other, str):
            # Compare against single-element route
            return len(self.elements) == 1 and self.elements[0] == other
        return super().__eq__(other)


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
        # Convert raw routes to typed configs
        self.failover_routes: dict[str, FailoverRouteConfig] = {}
        if failover_routes:
            for backend, route in failover_routes.items():
                if isinstance(route, dict):
                    self.failover_routes[backend] = FailoverRouteConfig.model_validate(
                        route
                    )
                elif isinstance(route, FailoverRouteConfig):
                    self.failover_routes[backend] = route

    def get_failover_route(self, backend_type: str) -> FailoverRouteConfig | None:
        """Get the failover route for a backend type.

        Args:
            backend_type: The backend type to get the failover route for

        Returns:
            The failover route config, or None if no failover route is configured
        """
        failover_route = self.failover_routes.get(backend_type)
        if failover_route:
            if is_log_level_enabled(logger, logging.INFO):
                logger.info(
                    "Found failover route",
                    backend_type=backend_type,
                    failover_route=failover_route.model_dump(),
                )
        else:
            if is_log_level_enabled(logger, logging.DEBUG):
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
        route_data = backend_config.failover_routes.get(model)
        if not route_data:
            # Support conventional fallback keys like "default" or "*"
            fallback_route = None
            for key, candidate in backend_config.failover_routes.items():
                try:
                    key_normalized = str(key).strip().lower()
                except (TypeError, AttributeError):
                    logger.warning(
                        "Failed to normalize failover route key, skipping",
                        key=key,
                        exc_info=True,
                    )
                    key_normalized = ""

                if key_normalized in {"default", "*"}:
                    fallback_route = candidate
                    break

            if fallback_route:
                route_data = fallback_route
            else:
                if is_log_level_enabled(logger, logging.DEBUG):
                    logger.debug("No failover route found for model", model=model)
                return []

        try:
            route_config = FailoverRouteConfig.model_validate(route_data)
        except ValidationError:
            logger.warning(
                "Invalid failover route configuration format (validation error)",
                exc_info=True,
            )
            return []
        except (TypeError, AttributeError) as e:
            # Expected exceptions from type checking or attribute access
            logger.warning(
                "Invalid failover route configuration format (type/attribute error): %s",
                e,
                exc_info=True,
            )
            return []
        except Exception as e:
            # Unexpected exceptions should be logged with full context
            logger.warning(
                "Unexpected error validating failover route configuration: %s",
                e,
                exc_info=True,
            )
            return []

        policy = route_config.policy
        elements = route_config.elements

        if is_log_level_enabled(logger, logging.DEBUG):
            logger.debug(
                "Getting failover attempts",
                model=model,
                policy=policy,
                elements=elements,
            )

        attempts = []
        for element in elements:
            try:
                parsed = parse_model_backend(element, default_backend=backend_type)
                elem_backend = parsed.backend_type
                elem_model = parsed.model_name
                if not elem_backend or not elem_model:
                    continue
                attempts.append(FailoverAttempt(backend=elem_backend, model=elem_model))
            except (ValidationError, TypeError, AttributeError) as e:
                # Expected exceptions from Pydantic validation or type/attribute errors
                logger.warning(
                    "Failed to parse failover route element (expected error): %s",
                    e,
                    element=element,
                    exc_info=True,
                )
                continue
            except Exception as e:
                # Unexpected exceptions should be logged with full context
                logger.warning(
                    "Unexpected error parsing failover route element: %s",
                    e,
                    element=element,
                    exc_info=True,
                )
                continue

        return attempts

    def add_failover_route(
        self,
        backend_type: str,
        failover_route: FailoverRouteConfig | dict[str, Any] | str,
    ) -> None:
        """Add a failover route.

        Args:
            backend_type: The backend type to add a failover route for
            failover_route: The failover route to add (config object, dict, or string)
        """
        typed_route = FailoverRouteConfig.model_validate(failover_route)

        self.failover_routes[backend_type] = typed_route
        if is_log_level_enabled(logger, logging.INFO):
            logger.info(
                "Added failover route",
                backend_type=backend_type,
                failover_route=typed_route.model_dump(),
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
        if is_log_level_enabled(logger, logging.DEBUG):
            logger.debug("No failover route to remove", backend_type=backend_type)
        return False

    def get_all_failover_routes(self) -> dict[str, FailoverRouteConfig]:
        """Get all failover routes.

        Returns:
            A dictionary mapping backend types to failover route configurations
        """
        return dict(self.failover_routes)

    def clear_failover_routes(self) -> None:
        """Clear all failover routes."""
        self.failover_routes.clear()
        logger.info("Cleared all failover routes")
