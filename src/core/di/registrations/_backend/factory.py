"""
Backend factory and config registration helpers.

Handles registration of:
- Backend Factory
- Backend Configuration Provider
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_backend_factory(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register backend factory with HTTP client dependency."""
    try:
        import httpx

        from src.core.services.backend_factory import BackendFactory

        def backend_factory_factory(provider: IServiceProvider) -> BackendFactory:
            """Factory function for creating BackendFactory with dependencies."""
            from src.core.services.backend_registry import BackendRegistry
            from src.core.services.translation_service import TranslationService

            httpx_client: httpx.AsyncClient = provider.get_required_service(
                httpx.AsyncClient
            )
            backend_registry_instance: BackendRegistry = provider.get_required_service(
                BackendRegistry
            )
            app_config: AppConfig = provider.get_required_service(AppConfig)
            translation_service: TranslationService = provider.get_required_service(
                TranslationService
            )

            # Get endpoint registry if available (for health checks)
            endpoint_registry = None
            try:
                from src.core.services.health.endpoint_registry import (
                    EndpointRegistry,
                )

                endpoint_registry = provider.get_service(EndpointRegistry)
            except (RuntimeError, ValueError, TypeError, AttributeError, KeyError):
                # Expected exceptions from service resolution (service not registered or resolution failed)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to resolve EndpointRegistry for BackendFactory; proceeding without health checks",
                        exc_info=True,
                    )
                # Health checks not enabled or not yet registered
            except Exception as e:
                # Unexpected exceptions during service resolution - log at warning level
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error resolving EndpointRegistry for BackendFactory: %s",
                        e,
                        exc_info=True,
                    )
                # Proceed without health checks

            # Get backend notifier if available (for health notifications)
            backend_notifier = None
            try:
                from src.core.services.health.backend_notifier import (
                    BackendHealthNotifier,
                )

                backend_notifier = provider.get_service(BackendHealthNotifier)
            except (RuntimeError, ValueError, TypeError, AttributeError, KeyError):
                # Expected exceptions from service resolution (service not registered or resolution failed)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to resolve BackendHealthNotifier for BackendFactory; proceeding without health notifications",
                        exc_info=True,
                    )
                # Health notifications not enabled or not yet registered
            except Exception as e:
                # Unexpected exceptions during service resolution - log at warning level
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error resolving BackendHealthNotifier for BackendFactory: %s",
                        e,
                        exc_info=True,
                    )
                # Proceed without health notifications

            # Get activity tracker if available (for connection monitoring)
            activity_tracker = None
            try:
                from src.core.services.connection_activity_tracker import (
                    ConnectionActivityTracker,
                )

                activity_tracker = provider.get_service(ConnectionActivityTracker)
            except (RuntimeError, ValueError, TypeError, AttributeError, KeyError):
                # Expected exceptions from service resolution (service not registered or resolution failed)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to resolve ConnectionActivityTracker for BackendFactory; proceeding without activity tracking",
                        exc_info=True,
                    )
                # Activity tracking not enabled or not yet registered
            except Exception as e:
                # Unexpected exceptions during service resolution - log at warning level
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error resolving ConnectionActivityTracker for BackendFactory: %s",
                        e,
                        exc_info=True,
                    )
                # Proceed without activity tracking

            return BackendFactory(  # DI-bypass (factory construction)
                httpx_client,
                backend_registry_instance,
                app_config,
                translation_service,
                endpoint_registry,
                backend_notifier,
                activity_tracker,
            )

        register_singleton_if_absent(
            services,
            BackendFactory,
            implementation_factory=backend_factory_factory,
        )
        try:
            from src.core.interfaces.backend_factory_interface import IBackendFactory

            register_singleton_if_absent(
                services,
                cast(type, IBackendFactory),
                implementation_factory=lambda p: p.get_required_service(BackendFactory),
            )
        except ImportError:
            pass

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered backend factory with dependencies")
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register backend factory: %s", e)


def register_backend_config_provider(services: ServiceCollection) -> None:
    """Register backend configuration provider."""
    try:
        from src.core.interfaces.backend_config_provider_interface import (
            IBackendConfigProvider,
        )
        from src.core.services.backend_config_provider import BackendConfigProvider

        def backend_config_provider_factory(
            provider: IServiceProvider,
        ) -> BackendConfigProvider:
            """Factory function for creating BackendConfigProvider."""
            app_config = provider.get_required_service(AppConfig)
            return BackendConfigProvider(app_config)

        register_singleton_if_absent(
            services,
            BackendConfigProvider,
            implementation_factory=backend_config_provider_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IBackendConfigProvider),
            implementation_factory=backend_config_provider_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered backend config provider")
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register backend config provider: %s", e)
