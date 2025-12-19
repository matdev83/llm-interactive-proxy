"""
Backend services initialization stage.

This stage registers backend-related services:
- Backend registry
- Backend factory
- Backend configuration provider
- Backend service (only when not already registered by CoreServicesStage)
"""

from __future__ import annotations

import logging
import os
from typing import cast

import httpx

from src.core.common.exceptions import InitializationError, ServiceResolutionError
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

                # Get endpoint registry if available (for health checks)
                endpoint_registry = None
                try:
                    from src.core.services.health.endpoint_registry import (
                        EndpointRegistry,
                    )

                    endpoint_registry = provider.get_service(EndpointRegistry)
                except Exception:
                    pass  # Health checks not enabled or not yet registered

                # Get backend notifier if available (for health notifications)
                backend_notifier = None
                try:
                    from src.core.services.health.backend_notifier import (
                        BackendHealthNotifier,
                    )

                    backend_notifier = provider.get_service(BackendHealthNotifier)
                except Exception:
                    pass  # Health notifications not enabled or not yet registered

                # Get activity tracker if available (for connection monitoring)
                activity_tracker = None
                try:
                    from src.core.services.connection_activity_tracker import (
                        ConnectionActivityTracker,
                    )

                    activity_tracker = provider.get_service(ConnectionActivityTracker)
                except Exception:
                    pass  # Activity tracking not enabled or not yet registered

                return BackendFactory(  # noqa: DI-bypass (factory construction)
                    httpx_client,
                    backend_registry_instance,
                    app_config,
                    translation_service,
                    endpoint_registry,
                    backend_notifier,
                    activity_tracker,
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

            services.add_singleton(
                TranslatorRegistry, implementation_factory=_translator_registry_factory
            )

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
        # CoreServicesStage calls `register_core_services(...)`, which registers
        # `BackendService` + `IBackendService` along with the extracted refactoring
        # services. In the default stage order, this BackendStage runs after
        # CoreServicesStage, so re-registering here would override the fully-wired
        # BackendService and silently bypass DI for the extracted services.
        descriptors = getattr(services, "_descriptors", {})
        if BackendFactory in descriptors:
            # BackendFactory is frequently (re)registered by this stage; do not treat
            # it as a signal for BackendService wiring.
            pass

        try:
            from src.core.interfaces.backend_config_provider_interface import (
                IBackendConfigProvider,
            )
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.services.backend_service import BackendService
            from src.core.services.rate_limiter import RateLimiter

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

            def backend_service_factory(provider: IServiceProvider) -> BackendService:
                """Factory function for creating BackendService with all dependencies.

                This factory mirrors the dependency resolution pattern from
                register_core_services._backend_service_factory to ensure
                consistent wiring across composition roots (Requirement 2.4).
                """
                import contextlib
                from typing import cast

                from src.core.config.app_config import AppConfig
                from src.core.interfaces.backend_completion_flow_interface import (
                    IBackendCompletionFlow,
                )
                from src.core.interfaces.backend_lifecycle_manager_interface import (
                    IBackendLifecycleManager,
                )
                from src.core.interfaces.backend_model_resolver_interface import (
                    IBackendModelResolver,
                )
                from src.core.interfaces.exception_normalizer_interface import (
                    IExceptionNormalizer,
                )
                from src.core.interfaces.failover_interface import (
                    IFailoverCoordinator,
                    IFailoverStrategy,
                )
                from src.core.interfaces.failover_planner_interface import (
                    IFailoverPlanner,
                )
                from src.core.interfaces.failure_strategy_interface import (
                    IFailureHandlingStrategy,
                )
                from src.core.interfaces.model_alias_resolver_interface import (
                    IModelAliasResolver,
                )
                from src.core.interfaces.planning_phase_manager_interface import (
                    IPlanningPhaseManager,
                )
                from src.core.interfaces.reasoning_config_applicator_interface import (
                    IReasoningConfigApplicator,
                )
                from src.core.interfaces.stream_formatting_interface import (
                    IStreamFormattingService,
                )
                from src.core.interfaces.stream_session_id_resolver_interface import (
                    IStreamSessionIdResolver,
                )
                from src.core.interfaces.uri_parameter_applicator_interface import (
                    IURIParameterApplicator,
                )
                from src.core.interfaces.usage_tracking_interface import (
                    IUsageTrackingService,
                )
                from src.core.interfaces.usage_tracking_wrapper_interface import (
                    IUsageTrackingWrapper,
                )
                from src.core.interfaces.wire_capture_interface import IWireCapture
                from src.core.services.backend_factory import BackendFactory
                from src.core.services.backend_routing_service import (
                    BackendRoutingService,
                )
                from src.core.services.resilience.coordinator import (
                    ResilienceCoordinator,
                )

                # Required services
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

                # Optional failover services
                failover_coordinator: IFailoverCoordinator | None = None
                with contextlib.suppress(Exception):
                    failover_coordinator = provider.get_service(
                        cast(type, IFailoverCoordinator)
                    )

                failover_strategy: IFailoverStrategy | None = None
                try:
                    if (
                        app_state.get_use_failover_strategy()
                        and failover_coordinator is not None
                    ):
                        from src.core.services.failover_strategy import (
                            DefaultFailoverStrategy,
                        )

                        failover_strategy = DefaultFailoverStrategy(
                            failover_coordinator
                        )
                except (AttributeError, ImportError, TypeError) as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to enable failover strategy: %s", e, exc_info=True
                        )

                # Optional infrastructure services
                wire_capture: IWireCapture | None = provider.get_service(
                    cast(type, IWireCapture)
                )
                routing_service: BackendRoutingService | None = provider.get_service(
                    BackendRoutingService
                )
                resilience_coordinator: ResilienceCoordinator | None = (
                    provider.get_service(ResilienceCoordinator)
                )
                # Resolve failure handling strategy from DI or construct from config
                from src.core.di.registration_helpers.failure_handling import (
                    resolve_failure_strategy,
                )

                failure_handling_strategy: IFailureHandlingStrategy | None = (
                    resolve_failure_strategy(provider, app_config, routing_service)
                )
                usage_tracking_service: IUsageTrackingService | None = (
                    provider.get_service(cast(type, IUsageTrackingService))
                )

                # Required extracted services (Phase 1-3 collaborators)
                stream_formatting_service: IStreamFormattingService = (
                    provider.get_required_service(cast(type, IStreamFormattingService))
                )
                usage_tracking_wrapper: IUsageTrackingWrapper = (
                    provider.get_required_service(cast(type, IUsageTrackingWrapper))
                )
                model_alias_resolver: IModelAliasResolver = (
                    provider.get_required_service(cast(type, IModelAliasResolver))
                )
                exception_normalizer: IExceptionNormalizer = (
                    provider.get_required_service(cast(type, IExceptionNormalizer))
                )
                backend_lifecycle_manager: IBackendLifecycleManager = (
                    provider.get_required_service(cast(type, IBackendLifecycleManager))
                )
                planning_phase_manager: IPlanningPhaseManager = (
                    provider.get_required_service(cast(type, IPlanningPhaseManager))
                )
                reasoning_config_applicator: IReasoningConfigApplicator = (
                    provider.get_required_service(
                        cast(type, IReasoningConfigApplicator)
                    )
                )
                uri_parameter_applicator: IURIParameterApplicator = (
                    provider.get_required_service(cast(type, IURIParameterApplicator))
                )
                stream_session_id_resolver: IStreamSessionIdResolver = (
                    provider.get_required_service(cast(type, IStreamSessionIdResolver))
                )
                backend_model_resolver: IBackendModelResolver = (
                    provider.get_required_service(cast(type, IBackendModelResolver))
                )
                failover_planner: IFailoverPlanner = provider.get_required_service(
                    cast(type, IFailoverPlanner)
                )
                backend_completion_flow: IBackendCompletionFlow = (
                    provider.get_required_service(cast(type, IBackendCompletionFlow))
                )

                # Construct BackendService with all explicit dependencies (Requirement 2.4)
                return BackendService(  # noqa: DI-bypass (factory construction)
                    backend_factory,
                    rate_limiter,
                    app_config,
                    session_service,
                    app_state,
                    backend_config_provider=backend_config_provider,
                    failover_coordinator=failover_coordinator,
                    failover_strategy=failover_strategy,
                    wire_capture=wire_capture,
                    routing_service=routing_service,
                    resilience_coordinator=resilience_coordinator,
                    failure_handling_strategy=failure_handling_strategy,
                    usage_tracking_service=usage_tracking_service,
                    stream_formatting_service=stream_formatting_service,
                    usage_tracking_wrapper=usage_tracking_wrapper,
                    model_alias_resolver=model_alias_resolver,
                    exception_normalizer=exception_normalizer,
                    backend_lifecycle_manager=backend_lifecycle_manager,
                    planning_phase_manager=planning_phase_manager,
                    reasoning_config_applicator=reasoning_config_applicator,
                    uri_parameter_applicator=uri_parameter_applicator,
                    stream_session_id_resolver=stream_session_id_resolver,
                    backend_model_resolver=backend_model_resolver,
                    failover_planner=failover_planner,
                    backend_completion_flow=backend_completion_flow,
                )

            services.add_singleton(
                BackendService, implementation_factory=backend_service_factory
            )

            services.add_singleton_factory(
                cast(type, IBackendService),
                implementation_factory=lambda provider: provider.get_required_service(
                    BackendService
                ),
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
            except Exception:
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
                logger.error(f"Backend services validation failed: {e}")
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
                from src.core.app.controllers.models_controller import (
                    _resolve_backend_factory_from_provider,
                )

                backend_factory_service = _resolve_backend_factory_from_provider(
                    provider
                )

            if backend_factory_service is None:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Could not create or resolve BackendFactory for validation."
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
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            f"Failed to validate backend '{backend_name}': {e}"
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
                    f"Failed to get BackendFactory service for validation: {e}"
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
                        translation_service = TranslationService()  # noqa: DI-bypass

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
                                    f"Skipping validation for backend '{backend_name}' due to missing dependency: {e}"
                                )
                            continue
                        raise
                    except Exception as create_error:
                        # Backends like 'gemini' may fail during early validation if
                        # required parameters are not yet available. Log at DEBUG level.
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                f"Backend '{backend_name}' cannot be instantiated during validation: {create_error}"
                            )
                        continue

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
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            f"Failed to validate backend '{backend_name}': {e}"
                        )

        return functional_backends

    def _register_validation_http_client(self, services: ServiceCollection) -> None:
        """Register an HTTP client when infrastructure stage has not run yet."""
        try:
            client = httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                trust_env=False,
            )
        except Exception:
            client = httpx.AsyncClient(
                http2=False,
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                trust_env=False,
            )

        services.add_instance(httpx.AsyncClient, client)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Registered temporary HTTP client for backend validation before infrastructure stage"
            )

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
