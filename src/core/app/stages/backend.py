"""
Backend services initialization stage.

This stage registers backend-related services:
- Backend registry
- Backend factory
- Backend configuration provider
- Backend service (only when not already registered by CoreServicesStage)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import cast

import httpx

from src.core.common.exceptions import InitializationError, ServiceResolutionError
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider
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

    def __init__(self) -> None:
        """Initialize the backend stage."""
        super().__init__()
        # Track validation HTTP client to ensure cleanup on failure
        self._validation_client: httpx.AsyncClient | None = None
        # Track cleanup tasks to prevent resource leaks
        # Use regular set instead of WeakSet to prevent premature garbage collection
        # before tasks complete, which could lead to HTTP client leaks
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    @property
    def name(self) -> str:
        return "backends"

    def get_dependencies(self) -> list[str]:
        return ["infrastructure"]

    def get_description(self) -> str:
        return "Register backend services (registry, factory, service)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register backend services."""
        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Initializing backend services...")

            # Import connectors package to trigger backend registrations via side effects
            import importlib

            importlib.import_module("src.connectors")
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Imported connectors, registered backends: {backend_registry.get_registered_backends()}"
                )

            # Validate static_route backend early - fail fast if invalid
            self._validate_static_route_backend(config)

            # Backend registrations are now handled by backend registrar
            # Register backend services via registrar
            from src.core.di.registrations import backend

            backend.register(services, config)

            # BackendService registration is handled by core registrar or this stage
            # Check if already registered, if not register it here for backward compatibility
            self._register_backend_service(services)

            if logger.isEnabledFor(logging.INFO):
                logger.info("Backend services initialized successfully")
        finally:
            # Ensure validation client is cleaned up if stage fails
            await self._cleanup_validation_client()

    def _register_backend_service(self, services: ServiceCollection) -> None:
        """Register main backend service with all dependencies."""
        # CoreServicesStage calls `register_core_services(...)`, which registers
        # `BackendService` + `IBackendService` along with the extracted refactoring
        # services. In the default stage order, this BackendStage runs after
        # CoreServicesStage, so re-registering here would override the fully-wired
        # BackendService and silently bypass DI for the extracted services.
        descriptors = getattr(services, "_descriptors", {})
        if BackendFactory in descriptors:
            # BackendFactory is frequently (re)registered by this stage; do not treat
            # it as a signal for BackendService wiring.

            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.services.backend_service import BackendService

            # If BackendService / IBackendService is already registered, do not override.
            if (
                BackendService in descriptors
                or cast(type, IBackendService) in descriptors
            ):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "BackendService already registered; BackendStage will not override it"
                    )
                return

            # BackendService registration is handled by centralized registration
            # Import and use the centralized registration function
            from src.core.di.registrations._backend.main_service import (
                register_backend_service,
            )

            register_backend_service(services)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered backend service with all dependencies")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that backend services can be registered and backends are functional."""
        try:
            registered_backends = backend_registry.get_registered_backends()
            if not registered_backends:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("No backends registered in backend registry")
                return True  # Allow startup with no backends for testing

            if logger.isEnabledFor(logging.INFO):
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
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to check configured backends in config: %s",
                        e,
                        exc_info=True,
                    )
                has_configured = False

            if has_configured and not functional_backends:
                # Check if running in test environment
                import os

                is_test = "PYTEST_CURRENT_TEST" in os.environ
                if is_test:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "No functional backends found in test environment; allowing startup"
                        )
                    return True
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "No functional backends found! Proxy cannot operate without at least one working backend."
                    )
                return False

            if not functional_backends:
                # Allow startup only when no backends are configured (pure test/minimal env)
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "No functional backends found and none configured; continuing startup for minimal environments"
                    )
                return True

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Found {len(functional_backends)} functional backends: {', '.join(functional_backends)}"
                )
            return True

        except ImportError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Backend services validation failed: %s", e, exc_info=True)
            return False

    async def _validate_backend_functionality(
        self, services: ServiceCollection, config: AppConfig
    ) -> list[str]:
        """Validate that configured backends are functional.

        Returns:
            List of functional backend names
        """
        functional_backends: list[str] = []

        # Get configured backends from the config
        configured_backends = []
        if config.backends.default_backend and config.backends.default_backend.strip():
            configured_backends.append(config.backends.default_backend)

        if config.backends.static_route:
            static_backend = config.backends.static_route.split(":", 1)[0]
            if static_backend not in configured_backends:
                configured_backends.append(static_backend)

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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("No backends configured in app config")
            return []

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Checking functionality of configured backends: {', '.join(configured_backends)}"
            )

        # Use the BackendFactory from the service container for proper DI
        try:
            from src.core.services.backend_factory import BackendFactory

            provider = services.build_service_provider()

            # Manually create a backend_factory_service if not available
            backend_factory_service = provider.get_service(BackendFactory)
            if backend_factory_service is None:
                # This is expected during early validation before BackendStage executes.
                # Log at DEBUG level to reduce noise during normal startup.
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "BackendFactory service not available for validation check during early startup, creating a temporary one."
                    )
                # This is a workaround. The DI container should ideally be fully configured.
                # Replicating the logic from di/services.py's _backend_service_factory's manual creation
                try:
                    provider.get_required_service(httpx.AsyncClient)
                except ServiceResolutionError:
                    self._register_validation_http_client(services)
                    provider = services.build_service_provider()
                provider.get_required_service(AppConfig)
                try:
                    from src.core.app.controllers.models_controller import (
                        _resolve_backend_factory_from_provider,  # type: ignore[private]
                    )

                    backend_factory_service = _resolve_backend_factory_from_provider(
                        provider  # type: ignore[arg-type]
                    )
                except ServiceResolutionError as e:
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            "Could not create or resolve BackendFactory for validation: %s",
                            e,
                            exc_info=True,
                        )
                    return functional_backends

            for backend_name in configured_backends:
                try:
                    # Check if backend is registered
                    if backend_name not in backend_registry.get_registered_backends():
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Backend '{backend_name}' is configured but not registered"
                            )
                        continue

                    # Get backend configuration from app config
                    backend_config_attr = backend_name.replace("-", "_")
                    backend_config = getattr(config.backends, backend_config_attr, None)

                    if not backend_config:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"No configuration found for backend '{backend_name}', skipping validation"
                            )
                        continue

                    # Use BackendFactory to properly create and initialize the backend
                    backend = await backend_factory_service.ensure_backend(
                        backend_type=backend_name,
                        app_config=config,
                        backend_config=backend_config,
                    )

                    # Check if backend is functional
                    if hasattr(backend, "is_backend_functional"):
                        is_functional = backend.is_backend_functional()
                    else:
                        is_functional = getattr(backend, "is_functional", True)

                    if is_functional:
                        functional_backends.append(backend_name)
                        if logger.isEnabledFor(logging.INFO):
                            logger.info("Backend '%s' is functional", backend_name)
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
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            f"Failed to validate backend '{backend_name}': {e}",
                            exc_info=True,
                        )

        except ServiceResolutionError as exc:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Backend validation dependencies not ready; using temporary HTTP client. Error: %s",
                    exc,
                )
            functional_backends.extend(
                await self._manual_backend_validation(
                    configured_backends, services, config
                )
            )
        except InitializationError as exc:
            # This is expected during early validation before BackendStage has fully
            # initialized the BackendFactory. Log at DEBUG level to reduce noise.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "BackendFactory unavailable for validation during early startup; using manual backend checks instead: %s",
                    exc,
                )
            functional_backends.extend(
                await self._manual_backend_validation(
                    configured_backends, services, config
                )
            )
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failed to get BackendFactory service for validation: {e}",
                    exc_info=True,
                )
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Falling back to manual backend validation")
            functional_backends.extend(
                await self._manual_backend_validation(
                    configured_backends, services, config
                )
            )

        return functional_backends

    async def _manual_backend_validation(
        self,
        configured_backends: list[str],
        services: ServiceCollection,
        config: AppConfig,
    ) -> list[str]:
        """Perform backend validation using a temporary HTTP client."""
        from typing import cast

        functional_backends: list[str] = []

        if not configured_backends:
            return functional_backends

        from src.core.interfaces.translation_service_interface import (
            ITranslationService,
        )

        async with httpx.AsyncClient() as client:
            for backend_name in configured_backends:
                try:
                    if backend_name not in backend_registry.get_registered_backends():
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Backend '{backend_name}' is configured but not registered"
                            )
                        continue

                    backend_factory_func = backend_registry.get_backend_factory(
                        backend_name
                    )

                    try:
                        provider = services.build_service_provider()
                        if not provider.has_service(cast(type, ITranslationService)):
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    "TranslationService not found in container, registering temporary instance for validation"
                                )
                            from src.core.domain.translators.defaults import (
                                ensure_default_translator_factories_registered,
                            )
                            from src.core.domain.translators.registry import (
                                TranslatorRegistry,
                                get_global_translator_registry,
                            )

                            def _translator_registry_factory(
                                p: IServiceProvider,
                            ) -> TranslatorRegistry:
                                registry = get_global_translator_registry()
                                ensure_default_translator_factories_registered(registry)
                                return registry

                            services.add_singleton(
                                TranslatorRegistry,
                                implementation_factory=_translator_registry_factory,
                            )

                            services.add_singleton(TranslationService)
                            services.add_singleton(
                                cast(type, ITranslationService),
                                implementation_factory=lambda p: p.get_required_service(
                                    TranslationService
                                ),
                            )
                        translation_service: (
                            ITranslationService
                        ) = services.build_service_provider().get_required_service(
                            cast(type, ITranslationService)
                        )
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Could not resolve TranslationService from container, creating temporary instance: {e}"
                            )
                        provider = services.build_service_provider()
                        translation_service = provider.get_required_service(
                            TranslationService
                        )  # Use DI container

                    try:
                        backend = backend_factory_func(
                            client, config, translation_service
                        )

                        backend_config_attr = backend_name.replace("-", "_")
                        backend_config_data = getattr(
                            config.backends, backend_config_attr, None
                        )

                        init_config: dict[str, object] = {}
                        if backend_config_data:
                            if (
                                hasattr(backend_config_data, "api_key")
                                and backend_config_data.api_key
                            ):
                                init_config["api_key"] = backend_config_data.api_key[0]
                            if (
                                hasattr(backend_config_data, "api_url")
                                and backend_config_data.api_url
                            ):
                                init_config["api_base_url"] = (
                                    backend_config_data.api_url
                                )
                            if hasattr(backend_config_data, "extra"):
                                init_config.update(backend_config_data.extra)

                        if backend_name == "gemini":
                            init_config["key_name"] = "gemini"
                            if "api_base_url" in init_config:
                                init_config["gemini_api_base_url"] = init_config.pop(
                                    "api_base_url"
                                )
                        elif backend_name == "anthropic":
                            init_config["key_name"] = "anthropic"
                        elif backend_name == "openrouter":
                            init_config["key_name"] = "openrouter"
                            from src.core.config.config_loader import (
                                get_openrouter_headers,
                            )

                            init_config["openrouter_headers_provider"] = (
                                get_openrouter_headers
                            )
                            if "api_base_url" not in init_config:
                                init_config["api_base_url"] = (
                                    "https://openrouter.ai/api/v1"
                                )

                        await backend.initialize(**init_config)
                    except TypeError as e:
                        if "required positional argument" in str(e) or "missing" in str(
                            e
                        ):
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    "Skipping validation for backend '%s' due to missing dependency: %s",
                                    backend_name,
                                    e,
                                )
                            continue
                        raise
                    except Exception as create_error:
                        # Backends like 'gemini' may fail during early validation if
                        # required parameters are not yet available. Log at DEBUG level.
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Backend '%s' cannot be instantiated during validation: %s",
                                backend_name,
                                create_error,
                            )
                        continue

                    if hasattr(backend, "is_backend_functional"):
                        is_functional = backend.is_backend_functional()
                    else:
                        is_functional = getattr(backend, "is_functional", True)

                    if is_functional:
                        functional_backends.append(backend_name)
                        if logger.isEnabledFor(logging.INFO):
                            logger.info("Backend '%s' is functional", backend_name)
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
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            f"Failed to validate backend '{backend_name}': {e}"
                        )

        return functional_backends

    def _register_validation_http_client(self, services: ServiceCollection) -> None:
        """Register an HTTP client when infrastructure stage has not run yet."""
        # Check if client already exists to avoid replacing and leaking
        provider = services.build_service_provider()
        existing_client = provider.get_service(httpx.AsyncClient)
        if existing_client is not None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "HTTP client already registered; reusing existing instance"
                )
            return

        client: httpx.AsyncClient | None = None
        try:
            try:
                client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )
            except (
                ValueError,
                RuntimeError,
                OSError,
                ImportError,
                httpx.UnsupportedProtocol,
            ) as e:
                # Fallback to HTTP/1.1 if HTTP/2 setup fails
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "HTTP/2 client creation failed, falling back to HTTP/1.1: %s",
                        e,
                        exc_info=True,
                    )
                client = httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )

            # Track client for cleanup if stage fails
            # Assign immediately after creation to ensure cleanup even if exception occurs later
            self._validation_client = client

            # Register client in DI - it will be cleaned up during app shutdown
            # The DI container handles httpx.AsyncClient cleanup automatically
            services.add_instance(httpx.AsyncClient, client)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Registered temporary HTTP client for backend validation before infrastructure stage"
                )
        except Exception as e:
            # If exception occurs after client creation but before assignment/registration,
            # ensure client is cleaned up to prevent leak
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Exception during validation client creation, attempting cleanup: %s",
                    e,
                    exc_info=True,
                )
            if client is not None and self._validation_client is None:
                # Client was created but not assigned - clean it up immediately
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Schedule cleanup task and track it to prevent resource leaks
                        cleanup_task = asyncio.create_task(client.aclose())
                        self._cleanup_tasks.add(cleanup_task)
                    else:
                        loop.run_until_complete(client.aclose())
                except (RuntimeError, AttributeError):
                    # No event loop - client will be cleaned up by finalizer
                    pass
            raise

    async def _cleanup_validation_client(self) -> None:
        """Clean up validation HTTP client if stage fails before infrastructure stage runs."""
        if self._validation_client is not None:
            client = self._validation_client
            self._validation_client = None
            try:
                if not client.is_closed:
                    await client.aclose()
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Cleaned up validation HTTP client")
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Error cleaning up validation HTTP client: %s", e)

        # Wait for any pending cleanup tasks to complete
        # Ensure all tasks are properly awaited/cancelled even if cleanup fails
        pending_tasks = [t for t in self._cleanup_tasks if not t.done()]
        if pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Timeout waiting for cleanup tasks, cancelling")
                # Cancel all pending tasks
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                # Await cancelled tasks to ensure they complete
                # This prevents task references from preventing garbage collection
                try:
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Error awaiting cancelled cleanup tasks: %s", e)
            except Exception as e:
                # If gather itself fails, still cancel and await tasks
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Error during cleanup task gather: %s", e)
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.gather(*pending_tasks, return_exceptions=True)

        # Clear the cleanup tasks set to prevent memory leaks
        # This ensures task references don't prevent garbage collection
        self._cleanup_tasks.clear()

    def _validate_static_route_backend(self, config: AppConfig) -> None:
        """Validate that static_route backend exists and is registered.

        Raises:
            ValueError: If static_route specifies an invalid backend name
        """
        if not config.backends.static_route:
            return

        static_backend = config.backends.static_route.split(":", 1)[0]
        registered_backends = backend_registry.get_registered_backends()

        if static_backend not in registered_backends:
            available_backends = ", ".join(sorted(registered_backends))
            raise ValueError(
                f"Invalid backend '{static_backend}' specified in --static-route parameter.\n"
                f"Backend '{static_backend}' is not registered.\n"
                f"Available backends: {available_backends}\n"
                f"Current static_route value: '{config.backends.static_route}'\n"
                f"Expected format: <backend_name>:<model_name>\n"
                f"Example: --static-route gemini-oauth-plan:gemini-2.5-pro"
            )
