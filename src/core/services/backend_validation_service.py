"""Backend validation service for validating configured backends.

This module provides BackendValidationService which validates all configured
backends by creating them via the canonical BackendFactory path and checking
their functionality.

Feature: backend-stage-solid-refactoring
Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.10, 9.2, 11.2, 12.2
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from src.core.config.app_config import AppConfig, BackendConfig
from src.core.config.models.backends import BackendSettings
from src.core.interfaces.backend_factory_interface import IBackendFactory
from src.core.interfaces.backend_validator_interface import IBackendValidator
from src.core.interfaces.http_client_manager_interface import IHttpClientManager

if TYPE_CHECKING:
    from src.core.services.backend_registry import BackendRegistry

logger = logging.getLogger(__name__)


class BackendValidationService(IBackendValidator):
    """Service for validating backend configurations.

    Validates configured backends by creating them via the canonical factory path
    and checking their functionality. Preserves current startup behavior for
    pass/fail decisions and error logging.
    """

    def __init__(
        self,
        backend_factory: IBackendFactory,
        http_client_manager: IHttpClientManager,
        backend_registry: BackendRegistry,
    ) -> None:
        """Initialize the backend validation service.

        Args:
            backend_factory: Factory for creating backends via canonical path
            http_client_manager: Manager for validation-time HTTP client lifecycle
            backend_registry: Registry for checking registered backends
        """
        self._backend_factory = backend_factory
        self._http_client_manager = http_client_manager
        self._backend_registry = backend_registry

    async def validate_all(self, config: AppConfig) -> bool:
        """Validate all configured backends.

        Determines configured backend names from:
        - default_backend (if non-empty)
        - static_route backend part (split by ':', if no colon treat whole string)
        - explicit backend configs present on config.backends that have an api_key

        Filters to registered backends only. If none configured, logs warning and
        returns True. If none functional, fails fast in non-test environments.

        Args:
            config: The application configuration containing backend settings.

        Returns:
            True if validation passes and startup should continue, False otherwise.
        """
        # Determine configured backend names
        # We consider a backend "configured" if it appears in:
        # - default_backend (if non-empty)
        # - static_route backend part
        # - explicit backend configs with api_key
        # But we only validate backends that have an api_key configured
        configured_backends: set[str] = set()

        # Collect potential backend names from default_backend and static_route
        potential_backends: set[str] = set()

        # Add default_backend if non-empty
        if config.backends.default_backend:
            potential_backends.add(config.backends.default_backend)

        # Add backend from static_route if present
        if config.backends.static_route:
            static_route = config.backends.static_route
            if ":" in static_route:
                backend_name = static_route.split(":", 1)[0]
            else:
                backend_name = static_route
            if backend_name:
                potential_backends.add(backend_name)

        # Add explicit backend configs that have api_key
        # Note: BackendSettings auto-adds all registered backends with empty configs,
        # so we only consider backends that have an api_key as explicitly configured
        named = config.backends.get_named_backend_configs()
        for backend_name, backend_config in named.items():
            # Skip non-BackendConfig attributes and special fields
            if (
                backend_name.startswith("_")
                or backend_name == "default_backend"
                or backend_name == "static_route"
                or backend_name in BackendSettings.model_fields
                or not isinstance(backend_config, BackendConfig)
            ):
                continue

            # Only consider backends with api_key as explicitly configured
            if backend_config.api_key:
                potential_backends.add(backend_name)

        # Filter to only backends that have api_key configured
        for backend_name in potential_backends:
            maybe_cfg = named.get(backend_name)
            if isinstance(maybe_cfg, BackendConfig) and maybe_cfg.api_key:
                configured_backends.add(backend_name)

        # Filter to registered backends only
        registered_backends = set(self._backend_registry.get_registered_backends())
        configured_and_registered = configured_backends & registered_backends

        # If none configured, log warning and allow startup
        if not configured_and_registered:
            logger.warning(
                "No backends configured or all configured backends are unregistered"
            )
            return True

        # Ensure validation-time HTTP client exists
        try:
            self._http_client_manager.get_or_create_client()
        except Exception as e:
            logger.error(
                "Failed to create validation HTTP client: %s",
                e,
                exc_info=True,
            )
            return False

        # Validate each configured+registered backend
        functional_backends: list[str] = []
        non_functional_backends: list[tuple[str, list[str]]] = []

        for backend_name in configured_and_registered:
            try:
                # Get backend config if available
                backend_config_value: BackendConfig | None = None
                if backend_name in named:
                    config_value = named.get(backend_name)
                    if isinstance(config_value, BackendConfig):
                        backend_config_value = config_value

                # Create backend via canonical factory path
                backend = await self._backend_factory.ensure_backend(
                    backend_type=backend_name,
                    app_config=config,
                    backend_config=backend_config_value,
                )

                # Check if backend is functional
                if backend.is_backend_functional():
                    functional_backends.append(backend_name)
                else:
                    # Collect validation errors if available
                    validation_errors: list[str] = []
                    if hasattr(backend, "get_validation_errors"):
                        validation_errors = backend.get_validation_errors()

                    non_functional_backends.append((backend_name, validation_errors))

                    # Log error for non-functional backend
                    error_details = ""
                    if validation_errors:
                        error_details = f": {'; '.join(validation_errors)}"
                    logger.error(
                        "Backend '%s' is not functional%s",
                        backend_name,
                        error_details,
                    )

            except Exception as e:
                # Log exception and treat backend as non-functional
                logger.error(
                    "Failed to validate backend '%s': %s",
                    backend_name,
                    e,
                    exc_info=True,
                )
                non_functional_backends.append((backend_name, [str(e)]))

        # If at least one functional backend, allow startup
        if functional_backends:
            return True

        # If none functional, check test environment
        if os.environ.get("PYTEST_CURRENT_TEST"):
            logger.warning(
                "No functional backends found, but test environment detected - allowing startup"
            )
            return True

        # Fail fast in non-test environment
        logger.error("No functional backends found - startup cannot continue")
        return False
