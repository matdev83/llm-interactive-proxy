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
import os
from typing import cast

import httpx

from src.core.config.app_config import AppConfig
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
            from src.core.services.rate_limiter import RateLimiter

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

            def _backend_service_alias_factory(
                provider: IServiceProvider,
            ) -> BackendService:
                """Resolve the concrete BackendService singleton for the interface."""

                return provider.get_required_service(BackendService)

            services.add_singleton(
                cast(type, IBackendService),
                implementation_factory=_backend_service_alias_factory,
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

            # If there are configured backends but none are functional, fail validation
            has_configured = False
            try:
                # Mirror logic in _validate_backend_functionality to detect if any were configured
                configured: list[str] = []
                if (
                    config.backends.default_backend
                    and config.backends.default_backend.strip()
                ):
                    configured.append(config.backends.default_backend)
                for backend_name in [
                    "openai",
                    "anthropic",
                    "gemini",
                    "openrouter",
                    "qwen-oauth",
                ]:
                    backend_config = getattr(
                        config.backends, backend_name.replace("-", "_"), None
                    )
                    if backend_config and backend_name not in configured:
                        # Consider it configured if any api key-like field may be present (checked later)
                        configured.append(backend_name)
                has_configured = len(configured) > 0
            except Exception:
                has_configured = False

            if has_configured and not functional_backends:
                logger.error(
                    "No functional backends found! Proxy cannot operate without at least one working backend."
                )
                return False

            if not functional_backends:
                # Allow startup only when no backends are configured (pure test/minimal env)
                logger.warning(
                    "No functional backends found and none configured; continuing startup for minimal environments"
                )
                return True

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

        # Get configured backends from the config
        configured_backends = []
        if config.backends.default_backend and config.backends.default_backend.strip():
            configured_backends.append(config.backends.default_backend)

        # Add other configured backends
        for backend_name in [
            "openai",
            "anthropic",
            "gemini",
            "openrouter",
            "qwen-oauth",
        ]:
            backend_config = getattr(
                config.backends, backend_name.replace("-", "_"), None
            )
            if backend_config and backend_name not in configured_backends:
                # Check for a direct API key or any numbered API key
                # An API key can be in the config or in the environment
                has_config_key = (
                    hasattr(backend_config, "api_key") and backend_config.api_key
                )

                # Check for numbered keys, e.g., OPENROUTER_API_KEY_1
                env_prefix = f"{backend_name.upper().replace('-', '_')}_API_KEY"
                has_env_key = any(key.startswith(env_prefix) for key in os.environ)

                if has_config_key or has_env_key:
                    configured_backends.append(backend_name)

        if not configured_backends:
            logger.warning("No backends configured in app config")
            return []

        logger.info(
            f"Checking functionality of configured backends: {', '.join(configured_backends)}"
        )

        # Use the BackendFactory from the service container for proper DI
        try:
            from src.core.services.backend_factory import BackendFactory
            from src.core.models.backend_config import BackendConfig

            backend_factory_service = services.build_service_provider().get_service(BackendFactory)

            for backend_name in configured_backends:
                try:
                    # Check if backend is registered
                    if backend_name not in backend_registry.get_registered_backends():
                        logger.warning(
                            f"Backend '{backend_name}' is configured but not registered"
                        )
                        continue

                    # Get backend configuration from app config
                    backend_config_attr = backend_name.replace("-", "_")
                    backend_config_data = getattr(config.backends, backend_config_attr, None)

                    if not backend_config_data:
                        logger.warning(
                            f"No configuration found for backend '{backend_name}', skipping validation"
                        )
                        continue

                    # Convert to BackendConfig model
                    backend_config = BackendConfig(
                        api_key=backend_config_data.api_key if hasattr(backend_config_data, 'api_key') else [],
                        api_url=getattr(backend_config_data, 'api_url', None),
                        extra=getattr(backend_config_data, 'extra', {})
                    )

                    # Use BackendFactory to properly create and initialize the backend
                    backend = await backend_factory_service.ensure_backend(
                        backend_type=backend_name,
                        app_config=config,
                        backend_config=backend_config
                    )

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

        except Exception as e:
            logger.error(f"Failed to get BackendFactory service for validation: {e}")
            # Fallback to manual validation if service container is not available
            logger.warning("Falling back to manual backend validation")

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

                        # Create backend instance
                        backend_factory_func = backend_registry.get_backend_factory(backend_name)

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
                            from src.core.services.translation_service import (
                                TranslationService,
                            )
                            translation_service = TranslationService()

                        # Create backend with available dependencies
                        try:
                            backend = backend_factory_func(client, config, translation_service)

                            # Build proper initialization config
                            backend_config_attr = backend_name.replace("-", "_")
                            backend_config_data = getattr(config.backends, backend_config_attr, None)

                            init_config = {}
                            if backend_config_data:
                                if hasattr(backend_config_data, 'api_key') and backend_config_data.api_key:
                                    init_config["api_key"] = backend_config_data.api_key[0]
                                if hasattr(backend_config_data, 'api_url') and backend_config_data.api_url:
                                    init_config["api_base_url"] = backend_config_data.api_url
                                if hasattr(backend_config_data, 'extra'):
                                    init_config.update(backend_config_data.extra)

                            # Backend-specific configuration mapping
                            if backend_name == "gemini":
                                init_config["key_name"] = "gemini"
                                if "api_base_url" in init_config:
                                    init_config["gemini_api_base_url"] = init_config.pop("api_base_url")
                            elif backend_name == "anthropic":
                                init_config["key_name"] = "anthropic"
                            elif backend_name == "openrouter":
                                init_config["key_name"] = "openrouter"
                                from src.core.config.config_loader import get_openrouter_headers
                                init_config["openrouter_headers_provider"] = get_openrouter_headers
                                if "api_base_url" not in init_config:
                                    init_config["api_base_url"] = "https://openrouter.ai/api/v1"

                            # Initialize backend with proper configuration
                            await backend.initialize(**init_config)

                        except TypeError as e:
                            if "required positional argument" in str(e) or "missing" in str(e):
                                logger.warning(
                                    f"Skipping validation for backend '{backend_name}' due to missing dependency: {e}"
                                )
                                continue
                            raise
                        except Exception as create_error:
                            logger.warning(
                                f"Backend '{backend_name}' cannot be instantiated during validation: {create_error}"
                            )
                            continue

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
