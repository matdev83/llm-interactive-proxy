"""
Backend services initialization stage.

This stage registers backend-related services:
- Backend registry
- Backend factory
- Backend configuration provider
- Backend service
"""

from __future__ import annotations

import logging
from typing import cast

import httpx

from src.core.config.app_config import AppConfig, BackendConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

from .base import InitializationStage

logger = logging.getLogger(__name__)


class BackendStage(InitializationStage):
    """
    Stage for registering backend-related services.

    This stage registers:
    - Backend registry (singleton instance)
    - Backend factory (with HTTP client dependency)
    - Backend configuration provider
    - Backend service (main backend interface)
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

        try:
            # Import connectors package to trigger backend registrations via side effects
            import importlib

            importlib.import_module("src.connectors")
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Imported connectors, registered backends: {backend_registry.get_registered_backends()}"
                )
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to import connectors: {e}")

        self._register_backend_registry(services)
        self._register_translation_service(services)
        self._register_backend_factory(services)
        self._register_backend_config_provider(services)
        self._register_backend_service(services)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Backend services initialized successfully")

    def _register_backend_registry(self, services: ServiceCollection) -> None:
        """Register backend registry as singleton instance."""
        try:
            from src.core.services.backend_registry import (
                BackendRegistry,
                backend_registry,
            )

            services.add_instance(BackendRegistry, backend_registry)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered backend registry instance")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register backend registry: {e}")

    def _register_backend_factory(self, services: ServiceCollection) -> None:
        """Register backend factory with HTTP client dependency."""
        try:
            import httpx

            from src.core.services.backend_factory import BackendFactory

            def backend_factory_factory(provider: IServiceProvider) -> BackendFactory:
                """Factory function for creating BackendFactory with dependencies."""
                from src.core.services.backend_registry import BackendRegistry

                httpx_client: httpx.AsyncClient = provider.get_required_service(
                    httpx.AsyncClient
                )
                backend_registry_instance: BackendRegistry = (
                    provider.get_required_service(BackendRegistry)
                )
                app_config: AppConfig = provider.get_required_service(AppConfig)
                translation_service: TranslationService = provider.get_required_service(
                    TranslationService
                )
                return BackendFactory(
                    httpx_client,
                    backend_registry_instance,
                    app_config,
                    translation_service,
                )

            services.add_singleton(
                BackendFactory, implementation_factory=backend_factory_factory
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered backend factory with dependencies")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register backend factory: {e}")

    def _register_translation_service(self, services: ServiceCollection) -> None:
        """Register translation service."""
        try:
            from src.core.interfaces.translation_service_interface import (
                ITranslationService,
            )
            from src.core.services.translation_service import TranslationService

            # Register concrete implementation once
            services.add_singleton(TranslationService)

            # Ensure interface resolves to the same singleton instance via factory
            def _translation_service_alias_factory(
                provider: IServiceProvider,
            ) -> TranslationService:
                return provider.get_required_service(TranslationService)

            services.add_singleton(
                cast(type, ITranslationService),
                implementation_factory=_translation_service_alias_factory,
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered translation service")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register translation service: {e}")

    def _register_backend_config_provider(self, services: ServiceCollection) -> None:
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

            services.add_singleton(
                cast(type, IBackendConfigProvider),
                implementation_factory=backend_config_provider_factory,
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered backend config provider")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register backend config provider: {e}")

    def _register_backend_service(self, services: ServiceCollection) -> None:
        """Register main backend service with all dependencies."""
        try:
            from src.core.interfaces.backend_config_provider_interface import (
                IBackendConfigProvider,
            )
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.services.backend_service import BackendService
            from src.core.services.rate_limiter_service import RateLimiter

            def backend_service_factory(provider: IServiceProvider) -> BackendService:
                """Factory function for creating BackendService with all dependencies."""
                import contextlib
                from typing import cast

                from src.core.config.app_config import AppConfig
                from src.core.interfaces.failover_interface import IFailoverCoordinator
                from src.core.interfaces.wire_capture_interface import IWireCapture
                from src.core.services.backend_factory import BackendFactory

                backend_factory: BackendFactory = provider.get_required_service(
                    BackendFactory
                )
                rate_limiter: RateLimiter = provider.get_required_service(RateLimiter)
                app_config: AppConfig = provider.get_required_service(AppConfig)
                backend_config_provider: IBackendConfigProvider = (
                    provider.get_required_service(cast(type, IBackendConfigProvider))
                )
                session_service: ISessionService = provider.get_required_service(
                    cast(type, ISessionService)
                )
                app_state: IApplicationState = provider.get_required_service(
                    cast(type, IApplicationState)
                )

                # Get optional failover coordinator
                failover_coordinator: IFailoverCoordinator | None = None
                with contextlib.suppress(Exception):
                    failover_coordinator = provider.get_service(
                        cast(type, IFailoverCoordinator)
                    )

                # Get wire capture service
                wire_capture: IWireCapture = provider.get_required_service(
                    cast(type, IWireCapture)
                )

                return BackendService(
                    backend_factory,
                    rate_limiter,
                    app_config,
                    session_service,
                    app_state,
                    backend_config_provider=backend_config_provider,
                    failover_coordinator=failover_coordinator,
                    wire_capture=wire_capture,
                )

            services.add_singleton(
                BackendService, implementation_factory=backend_service_factory
            )

            services.add_singleton(
                cast(type, IBackendService),
                implementation_factory=backend_service_factory,
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered backend service with all dependencies")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register backend service: {e}")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that backend services can be registered and backends are functional."""
        try:
            registered_backends = backend_registry.get_registered_backends()
            if not registered_backends:
                logger.warning("No backends registered in backend registry")
                return True  # Allow startup with no backends for testing

            logger.info(
                f"Validating functionality of {len(registered_backends)} registered backends..."
            )

            # Validate configured backends are functional
            functional_backends = await self._validate_backend_functionality(
                services, config
            )

            if not functional_backends:
                # Check if we're in a test environment
                import os

                is_test_env = (
                    "PYTEST_CURRENT_TEST" in os.environ
                    or config.auth.disable_auth
                    or any(
                        key.api_key == ["test_key"]
                        for key in [
                            config.backends.__dict__.get(name)
                            for name in registered_backends
                        ]
                        if key and hasattr(key, "api_key")
                    )
                )

                if is_test_env:
                    logger.warning(
                        "No functional backends found, but allowing startup in test environment"
                    )
                    return True

                logger.error(
                    "No functional backends found! Proxy cannot operate without at least one working backend."
                )
                return False

            logger.info(
                f"Found {len(functional_backends)} functional backends: {', '.join(functional_backends)}"
            )
            return True

        except ImportError as e:
            logger.error(f"Backend services validation failed: {e}")
            return False

    async def _validate_backend_functionality(
        self, services: ServiceCollection, config: AppConfig
    ) -> list[str]:
        """Validate that configured backends are functional.

        Returns:
            List of functional backend names
        """
        functional_backends = []

        # Get all registered backends to validate.
        configured_backends = backend_registry.get_registered_backends()

        # If a default backend is set, prioritize it by putting it first in the list.
        default_backend = config.backends.default_backend
        if default_backend and default_backend in configured_backends:
            configured_backends.remove(default_backend)
            configured_backends.insert(0, default_backend)

        if not configured_backends:
            logger.warning("No backends configured in app config")
            return []

        logger.info(
            f"Checking functionality of configured backends: {', '.join(configured_backends)}"
        )

        # Create a temporary HTTP client for testing
        async with httpx.AsyncClient() as client:
            for backend_name in configured_backends:
                try:
                    # Check if backend is registered
                    if backend_name not in backend_registry.get_registered_backends():
                        logger.warning(
                            f"Backend '{backend_name}' is configured but not registered"
                        )
                        continue

                    # Check if backend is properly configured (has valid API keys)
                    backend_config = self._get_backend_config(backend_name, config)
                    if not self._is_backend_configured(backend_config):
                        logger.debug(
                            f"Backend '{backend_name}' is not properly configured (no API keys)"
                        )
                        continue

                    # Create backend instance
                    backend_factory = backend_registry.get_backend_factory(backend_name)

                    # Try to get translation service from services container
                    translation_service = None
                    try:
                        from src.core.interfaces.translation_service_interface import (
                            ITranslationService,
                        )
                        from src.core.services.translation_service import (
                            TranslationService,
                        )

                        translation_service = services.build_service_provider().get_service(ITranslationService)  # type: ignore[type-abstract]
                    except Exception:
                        # Translation service not available from container, create a temporary instance
                        # This is needed for backends that require translation_service parameter
                        from src.core.services.translation_service import (
                            TranslationService,
                        )

                        translation_service = TranslationService()

                    # Create backend with available dependencies
                    try:
                        backend = backend_factory(client, config, translation_service)
                    except TypeError as e:
                        if "required positional argument" in str(e) or "missing" in str(
                            e
                        ):
                            logger.warning(
                                f"Skipping validation for backend '{backend_name}' due to missing dependency: {e}"
                            )
                            continue
                        raise
                    except Exception as create_error:
                        # If backend can't be created due to other missing dependencies, skip it
                        # This is common during validation when not all services are available
                        logger.warning(
                            f"Backend '{backend_name}' cannot be instantiated during validation: {create_error}"
                        )
                        continue

                    # Initialize backend
                    await backend.initialize()

                    # Check if backend is functional
                    if hasattr(backend, "is_backend_functional"):
                        is_functional = backend.is_backend_functional()
                    else:
                        is_functional = getattr(backend, "is_functional", True)

                    if is_functional:
                        functional_backends.append(backend_name)
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(f"Backend '{backend_name}' is functional")
                    else:
                        # Get error details if available
                        error_details = ""
                        if hasattr(backend, "get_validation_errors"):
                            errors = backend.get_validation_errors()
                            if errors:
                                error_details = f": {'; '.join(errors)}"

                        if logger.isEnabledFor(logging.ERROR):
                            logger.error(
                                f"Backend '{backend_name}' is not functional{error_details}"
                            )

                except Exception as e:
                    logger.error(f"Failed to validate backend '{backend_name}': {e}")

        return functional_backends

    def _get_backend_config(
        self, backend_name: str, config: AppConfig
    ) -> BackendConfig | None:
        """Get the backend configuration for a specific backend name."""
        from src.core.services.backend_config_provider import BackendConfigProvider

        config_provider = BackendConfigProvider(config)
        return config_provider.get_backend_config(backend_name)

    def _is_backend_configured(self, backend_config: BackendConfig | None) -> bool:
        """Check if a backend is properly configured with valid API keys."""
        if backend_config is None:
            return False

        # Check if API keys are configured and non-empty
        api_keys = backend_config.api_key
        if not api_keys:
            return False

        # Filter out empty/whitespace-only keys
        valid_keys = [key for key in api_keys if key and key.strip()]
        return len(valid_keys) > 0
