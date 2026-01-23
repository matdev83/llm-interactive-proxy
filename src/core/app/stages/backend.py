"""
Backend services initialization stage.

This stage registers backend-related services via DI registrar and delegates validation.
"""

from __future__ import annotations

import importlib
import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.backend_validator_interface import IBackendValidator
from src.core.services.backend_registry import backend_registry

from .base import InitializationStage

logger = logging.getLogger(__name__)


class BackendStage(InitializationStage):
    """
    Stage for registering backend-related services via DI registrar and delegating validation.
    """

    @property
    def name(self) -> str:
        return "backends"

    def get_dependencies(self) -> list[str]:
        return ["infrastructure"]

    def get_description(self) -> str:
        return "Register backend services (registry, factory, service)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register backend services."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing backend services...")

        # Initialize ApplicationStateService with default backend from config
        # This is critical for model replacement and token limit enforcement
        try:
            from src.core.interfaces.application_state_interface import (
                IApplicationState,
            )

            # Build a temporary provider to resolve IApplicationState
            provider = services.build_service_provider()
            app_state = provider.get_service(cast(type, IApplicationState))
            if app_state:
                default_backend = config.backends.default_backend
                if default_backend:
                    app_state.set_backend_type(default_backend)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Initialized application state with default backend: %s",
                            default_backend,
                        )
        except Exception as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to initialize application state with default backend: %s",
                    exc,
                    exc_info=True,
                )

        # Import connectors package to trigger backend registrations via side effects

        importlib.import_module("src.connectors")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Imported connectors, registered backends: {backend_registry.get_registered_backends()}"
            )

        # Backend registrations are now handled by backend registrar
        # Register backend services via registrar
        from src.core.di.registrations import backend

        backend.register(services, config)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Backend services initialized successfully")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that backend services can be registered and backends are functional."""
        from src.core.di.provider_lifecycle import get_current_service_provider

        # Resolve IBackendValidator from the validation provider installed by ApplicationBuilder
        provider = get_current_service_provider()
        validator: IBackendValidator = provider.get_required_service(
            cast(type, IBackendValidator)
        )

        # Delegate validation to the backend validation service
        return bool(await validator.validate_all(config))
