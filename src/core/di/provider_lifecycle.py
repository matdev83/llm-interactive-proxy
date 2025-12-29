"""Provider lifecycle management and post-build hooks.

This module manages the global service provider state and handles post-build
initialization hooks, separate from pure registration logic.
"""

from __future__ import annotations

import logging
import os
from typing import cast

from src.core.interfaces.di_interface import IServiceProvider

# Global provider state
_service_provider: IServiceProvider | None = None

logger = logging.getLogger(__name__)


def _get_di_diagnostics() -> bool:
    """Get DI diagnostics setting from environment."""
    return os.getenv("DI_STRICT_DIAGNOSTICS", "false").lower() in (
        "true",
        "1",
        "yes",
    )


def get_or_build_service_provider() -> IServiceProvider:
    """Get the global service provider or build one if it doesn't exist.

    This function requires that get_service_collection() is available from
    src.core.di.services to avoid circular imports.

    Returns:
        The global service provider
    """
    global _service_provider
    # Backward-compatibility: keep the legacy `src.core.di.services._service_provider`
    # variable in sync with the canonical provider lifecycle state. Some tests
    # reset the provider by assigning to the legacy variable directly.
    try:
        from src.core.di import services as di_services

        if hasattr(di_services, "_service_provider"):
            legacy_provider = di_services._service_provider
            if legacy_provider is None:
                _service_provider = None
            else:
                _service_provider = cast(IServiceProvider, legacy_provider)
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Failed to sync with legacy _service_provider", exc_info=True)
    if _service_provider is None:
        # Import here to avoid circular import
        from src.core.di.services import get_service_collection

        services = get_service_collection()
        if _get_di_diagnostics():
            di_logger = logging.getLogger("llm.di")
            if di_logger.isEnabledFor(logging.INFO):
                di_logger.info(
                    "Building service provider; descriptors=%d",
                    len(services._descriptors),
                )
        _service_provider = services.build_service_provider()
        # Register feature parity tracking after provider is built
        post_build_hooks(_service_provider)
        try:
            from src.core.di import services as di_services

            di_services._service_provider = _service_provider  # type: ignore[attr-defined]
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to sync legacy _service_provider after build", exc_info=True
                )
    return _service_provider


def set_service_provider(provider: IServiceProvider | None) -> None:
    """Set the global service provider (used for tests/late init).

    Args:
        provider: The ServiceProvider instance to set as the global provider, or None to reset
    """
    global _service_provider
    _service_provider = provider
    try:
        from src.core.di import services as di_services

        di_services._service_provider = provider  # type: ignore[attr-defined]
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to sync legacy _service_provider in set_service_provider",
                exc_info=True,
            )


def get_service_provider() -> IServiceProvider:
    """Return the global service provider, building it if necessary.

    This function returns the provider as-is without any self-healing behavior.
    Missing services will fail fast with ServiceResolutionError.

    Returns:
        The global service provider
    """
    return get_or_build_service_provider()


def post_build_hooks(provider: IServiceProvider) -> None:
    """Execute post-build hooks after provider is built.

    This includes feature parity registry initialization and other
    post-build setup that should happen once after the provider is built.

    Args:
        provider: The service provider that was just built
    """
    _initialize_feature_parity_registry(provider)
    _register_tool_call_handlers(provider)


def _initialize_feature_parity_registry(provider: IServiceProvider) -> None:
    """Initialize feature parity registry with all registered middleware.

    This registers all middleware and features with the parity registry
    for tracking streaming/non-streaming support.

    Args:
        provider: The service provider to extract middleware from
    """
    try:
        from src.core.interfaces.feature_parity import get_global_registry
        from src.core.interfaces.response_processor_interface import FeatureCapability

        registry = get_global_registry()

        # Register core features (IResponseFeature implementations)
        try:
            from src.core.services.response_middleware import (
                ContentFilterFeature,
                ResponseLoggingFeature,
            )

            registry.register_feature(ResponseLoggingFeature())
            registry.register_feature(ContentFilterFeature())
        except ImportError:
            pass

        try:
            from src.core.services.empty_response_middleware import EmptyResponseFeature

            registry.register_feature(EmptyResponseFeature())
        except ImportError:
            pass

        # Register LoopDetectionFeature with the ILoopDetector from DI
        try:
            from src.core.interfaces.loop_detector_interface import ILoopDetector
            from src.core.services.response_middleware import LoopDetectionFeature

            loop_detector = provider.get_service(cast(type, ILoopDetector))
            if loop_detector is not None:
                registry.register_feature(LoopDetectionFeature(loop_detector))
        except Exception:
            # Log at WARNING level since this is on a critical path for DI initialization
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Failed to register LoopDetectionFeature", exc_info=True)

        # Register middleware instances from the middleware manager
        try:
            from src.core.interfaces.response_processor_interface import (
                IResponseFeature,
                IResponseMiddleware,
            )
            from src.core.services.middleware_application_manager import (
                MiddlewareApplicationManager,
            )

            manager = provider.get_required_service(MiddlewareApplicationManager)
            for mw in manager._middleware:
                if isinstance(mw, IResponseFeature):
                    registry.register_feature(mw)
                elif isinstance(mw, IResponseMiddleware):
                    mw_name = type(mw).__name__
                    # All updated middleware now support both paths
                    registry.register_middleware(
                        mw,
                        declared_capability=FeatureCapability.BOTH,
                        name=mw_name,
                    )
        except Exception:
            # Log at WARNING level since this is on a critical path for DI initialization
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register middleware in parity registry", exc_info=True
                )

        parity_logger = logging.getLogger("llm.feature_parity")
        if parity_logger.isEnabledFor(logging.DEBUG):
            parity_logger.debug(
                "Feature parity registry initialized with %d features",
                len(registry.get_all_features()),
            )
    except Exception as e:
        # Don't fail startup due to parity registration issues
        init_logger = logging.getLogger(__name__)
        init_logger.warning(
            "Feature parity initialization skipped: %s", e, exc_info=True
        )


def _register_tool_call_handlers(provider: IServiceProvider) -> None:
    """Register tool call handlers with ToolCallReactorService.

    This function registers all handlers that should be available when
    the service provider is built, including:
    - Dangerous command handler (if enabled)
    - Pytest compression handler (if enabled)
    - Test execution reminder handler (if enabled)
    - Other handlers registered via stages

    Args:
        provider: The service provider to resolve services from
    """
    try:
        from src.core.config.app_config import AppConfig
        from src.core.services.tool_call_reactor_service import ToolCallReactorService

        reactor_service = provider.get_service(ToolCallReactorService)
        if reactor_service is None:
            return

        config = provider.get_service(AppConfig)
        if config is None:
            return

        reactor_config = getattr(config.session, "tool_call_reactor", None)
        if reactor_config is None or not getattr(reactor_config, "enabled", False):
            return

        # Register dangerous command handler if enabled
        try:
            from src.core.services.dangerous_command_service import (
                DangerousCommandService,
            )
            from src.core.services.tool_call_handlers.dangerous_command_handler import (
                DangerousCommandHandler,
            )

            dangerous_service = provider.get_service(DangerousCommandService)
            if dangerous_service is not None:
                dangerous_config = None
                if hasattr(config, "dangerous_commands"):
                    dangerous_config = getattr(config, "dangerous_commands", None)  # type: ignore[attr-defined]
                elif hasattr(config, "unified_security"):
                    unified_config = getattr(config, "unified_security", None)  # type: ignore[attr-defined]
                    if unified_config is not None:
                        dangerous_config = getattr(
                            unified_config, "dangerous_commands", None
                        )

                if dangerous_config is not None and getattr(
                    dangerous_config, "enabled", False
                ):
                    dangerous_handler = DangerousCommandHandler(
                        dangerous_service=dangerous_service, enabled=True
                    )
                    reactor_service.register_handler_sync(dangerous_handler)
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register dangerous command handler: {e}", exc_info=True
                )

        # Register droid path fix handler if enabled
        try:
            from src.core.services.tool_call_handlers.droid_antigravity_path_fix_handler import (
                DroidAntigravityPathFixHandler,
            )

            droid_path_fix_enabled = getattr(
                config.session, "droid_path_fix_enabled", False
            )
            if droid_path_fix_enabled:
                droid_path_fix_handler = DroidAntigravityPathFixHandler(enabled=True)
                reactor_service.register_handler_sync(droid_path_fix_handler)
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register droid path fix handler: {e}", exc_info=True
                )

        # Register pytest compression handler if enabled
        try:
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.pytest_compression_service import (
                PytestCompressionService,
            )
            from src.core.services.tool_call_handlers.pytest_compression_handler import (
                PytestCompressionHandler,
            )

            pytest_service = provider.get_service(PytestCompressionService)
            session_service = provider.get_service(cast(type, ISessionService))
            if pytest_service is not None and session_service is not None:
                pytest_compression_enabled = getattr(
                    config.session, "pytest_compression_enabled", True
                )
                if pytest_compression_enabled:
                    pytest_compression_handler = PytestCompressionHandler(
                        pytest_compression_service=pytest_service,
                        session_service=session_service,
                        enabled=True,
                    )
                    reactor_service.register_handler_sync(pytest_compression_handler)
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register pytest compression handler: {e}", exc_info=True
                )

        # Register pytest context saving handler if enabled
        try:
            from src.core.services.tool_call_handlers.pytest_context_saving_handler import (
                PytestContextSavingHandler,
            )

            pytest_context_saving_enabled = getattr(
                reactor_config, "pytest_context_saving_enabled", False
            )
            if pytest_context_saving_enabled:
                pytest_context_saving_handler = PytestContextSavingHandler(enabled=True)
                reactor_service.register_handler_sync(pytest_context_saving_handler)
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register pytest context saving handler: {e}",
                    exc_info=True,
                )

        # Register test execution reminder handler if enabled
        try:
            from src.services.test_execution_reminder.test_execution_reminder_handler import (
                TestExecutionReminderHandler,
            )

            test_execution_reminder_enabled = getattr(
                config, "test_execution_reminder_enabled", False
            )
            if test_execution_reminder_enabled:
                test_execution_reminder_message = getattr(
                    config, "test_execution_reminder_message", None
                )
                test_execution_reminder_handler = TestExecutionReminderHandler(
                    message=test_execution_reminder_message, enabled=True
                )
                reactor_service.register_handler_sync(test_execution_reminder_handler)

                # Register TestExecutionReminderEosSubscriber
                # Note: We create it here but start it in AppLifecycle._start_eos_subscribers
                try:
                    from src.core.interfaces.event_bus_interface import IEventBus
                    from src.services.test_execution_reminder.eos_subscriber import (
                        TestExecutionReminderEosSubscriber,
                    )

                    event_bus: IEventBus = provider.get_required_service(
                        cast(type, IEventBus)
                    )
                    eos_subscriber = TestExecutionReminderEosSubscriber(
                        event_bus=event_bus,
                        reminder_handler=test_execution_reminder_handler,
                    )
                    # Store the subscriber in provider for AppLifecycle to start/stop
                    # This is necessary because the handler is created inline here,
                    # so we can't register the subscriber as a service in DI
                    provider._test_execution_reminder_eos_subscriber = eos_subscriber  # type: ignore[attr-defined]
                except ImportError:
                    logger = logging.getLogger(__name__)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "TestExecutionReminderEosSubscriber not available, skipping"
                        )
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register test execution reminder handler: {e}",
                    exc_info=True,
                )

        # Register End-of-Session tool call handler if EoS is enabled
        try:
            from src.core.interfaces.end_of_session_service_interface import (
                IEndOfSessionService,
            )
            from src.core.services.end_of_session_tool_call_handler import (
                EndOfSessionToolCallHandler,
            )

            eos_service = provider.get_service(cast(type, IEndOfSessionService))  # type: ignore[type-abstract]
            if eos_service is not None:
                eos_config = config.end_of_session
                if eos_config.enabled and eos_config.detect_tool_completion:
                    eos_handler = EndOfSessionToolCallHandler(
                        end_of_session_service=eos_service,
                        config=eos_config,
                    )
                    reactor_service.register_handler_sync(eos_handler)
                    logger = logging.getLogger(__name__)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Registered EndOfSessionToolCallHandler")
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register End-of-Session tool call handler: {e}",
                    exc_info=True,
                )

        # Register unified steering handler if available
        try:
            from src.services.steering import UnifiedSteeringHandler

            unified_handler = provider.get_service(UnifiedSteeringHandler)
            if unified_handler is not None:
                reactor_service.register_handler_sync(unified_handler)
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register unified steering handler: {e}", exc_info=True
                )

        # Register unified tool security handler if available
        try:
            from src.core.services.unified_tool_security_handler import (
                UnifiedToolSecurityHandler,
            )

            unified_security_handler = provider.get_service(UnifiedToolSecurityHandler)
            if unified_security_handler is not None:
                reactor_service.register_handler_sync(unified_security_handler)
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register unified tool security handler: {e}",
                    exc_info=True,
                )

        # Register tool access control handler if policies are configured
        try:
            from src.core.services.tool_access_policy_service import (
                ToolAccessPolicyService,
            )
            from src.core.services.tool_call_handlers.tool_access_control_handler import (
                ToolAccessControlHandler,
            )

            access_policies = getattr(reactor_config, "access_policies", None)
            if access_policies and len(access_policies) > 0:
                policy_service = provider.get_service(ToolAccessPolicyService)
                if policy_service is not None:
                    logger = logging.getLogger(__name__)
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "ToolAccessControlHandler registered (%d policies loaded)",
                            len(access_policies),
                        )
                    tool_access_control_handler = ToolAccessControlHandler(
                        policy_service=policy_service,
                        priority=90,
                        reactor_service=reactor_service,
                    )
                    reactor_service.register_handler_sync(tool_access_control_handler)
        except Exception as e:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not register tool access control handler: {e}",
                    exc_info=True,
                )
    except Exception as e:
        logger = logging.getLogger(__name__)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Tool call handler registration skipped: {e}")
