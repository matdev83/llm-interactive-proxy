"""
Model replacement services registrar.

Registers the random model replacement service and interface binding when enabled.
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register model replacement services when enabled.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    if app_config is None:
        app_config = AppConfig()

    replacement_config = getattr(app_config, "replacement", None)

    enabled = getattr(replacement_config, "enabled", False)
    # Debug logging to investigate why replacement might be disabled contrary to expectations
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Registering replacement services. Config enabled: {enabled}")
        logger.debug(f"Replacement config: {replacement_config}")

    if not enabled:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Model replacement feature not active in this configuration pass"
            )
        return

    from src.core.interfaces.model_replacement_service_interface import (
        IModelReplacementService,
    )
    from src.core.services.backend_registry import BackendRegistry
    from src.core.services.model_replacement_service import ModelReplacementService

    def _replacement_service_factory(
        provider: IServiceProvider,
    ) -> ModelReplacementService:
        config = provider.get_required_service(AppConfig)
        backend_registry = provider.get_required_service(BackendRegistry)
        return ModelReplacementService(config.replacement, backend_registry)

    register_singleton_if_absent(
        services,
        ModelReplacementService,
        implementation_factory=_replacement_service_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, IModelReplacementService),
        implementation_factory=lambda provider: provider.get_required_service(
            ModelReplacementService
        ),
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered model replacement services")
