"""
Backend core services registration helpers.

Handles registration of:
- Backend Registry
- Translation Service
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_backend_registry(services: ServiceCollection) -> None:
    """Register backend registry as singleton instance."""
    try:
        from src.core.services.backend_registry import (
            BackendRegistry,
            backend_registry,
        )

        # Use the global backend registry instance so that connector auto-registration
        # (performed at import time) is visible to the DI container.
        register_singleton_if_absent(
            services, BackendRegistry, instance=backend_registry
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered backend registry instance")
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Could not register backend registry: {e}")


def register_translation_service(services: ServiceCollection) -> None:
    """Register translation service."""
    try:
        from src.core.domain.translators.defaults import (
            ensure_default_translator_factories_registered,
        )
        from src.core.domain.translators.registry import (
            TranslatorRegistry,
            get_global_translator_registry,
        )
        from src.core.interfaces.translation_service_interface import (
            ITranslationService,
        )
        from src.core.services.translation_service import TranslationService

        def _translator_registry_factory(
            provider: IServiceProvider,
        ) -> TranslatorRegistry:
            registry = get_global_translator_registry()
            ensure_default_translator_factories_registered(registry)
            return registry

        register_singleton_if_absent(
            services,
            TranslatorRegistry,
            implementation_factory=_translator_registry_factory,
        )

        register_singleton_if_absent(services, TranslationService)

        # Ensure interface resolves to the same singleton instance via factory
        def _translation_service_alias_factory(
            provider: IServiceProvider,
        ) -> TranslationService:
            return provider.get_required_service(TranslationService)

        register_singleton_if_absent(
            services,
            cast(type, ITranslationService),
            implementation_factory=_translation_service_alias_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered translation service")
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Could not register translation service: {e}")
