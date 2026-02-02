"""
Security registrar.

Registers sandboxing, path validation, and unified tool security services.
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_interface_and_implementation,
    register_singleton_if_absent,
)
from src.core.interfaces.access_mode_validator_interface import IAccessModeValidator
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.path_validator_interface import IPathValidator

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register security services.

    This registrar handles:
    - Sandboxing services
    - Path validation
    - Tool access control
    - Security policy enforcement
    - Access mode validation

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # Register path validation service (always available)
    _register_path_validation(services)

    # Register access mode validator (always available)
    _register_access_mode_validator(services)

    # Register unified tool security handler (if enabled)
    _register_unified_tool_security_handler(services, app_config)


def _register_path_validation(services: ServiceCollection) -> None:
    """Register path validation service and interface."""
    from src.core.services.path_validation_service import PathValidationService

    # Register PathValidationService as singleton
    register_singleton_if_absent(services, PathValidationService)

    # Register IPathValidator interface bound to PathValidationService
    register_interface_and_implementation(
        services,
        cast(type, IPathValidator),
        PathValidationService,
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered PathValidationService and IPathValidator")


def _register_access_mode_validator(services: ServiceCollection) -> None:
    """Register access mode validator service and interface."""
    from src.core.services.access_mode_validator import AccessModeValidator

    # Register AccessModeValidator as singleton
    register_singleton_if_absent(services, AccessModeValidator)

    # Register IAccessModeValidator interface bound to AccessModeValidator
    register_interface_and_implementation(
        services,
        cast(type, IAccessModeValidator),
        AccessModeValidator,
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered AccessModeValidator and IAccessModeValidator")


def _register_unified_tool_security_handler(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register unified tool security handler if enabled.

    Note: Handler registration with ToolCallReactorService happens post-build
    via provider lifecycle hooks, not during registration.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    if app_config is None:
        return

    reactor_config = getattr(app_config.session, "tool_call_reactor", None)
    if reactor_config is None or not getattr(reactor_config, "enabled", False):
        return

    dangerous_enabled = getattr(
        app_config.session, "dangerous_command_prevention_enabled", True
    )
    sandboxing_enabled = getattr(app_config.sandboxing, "enabled", False)

    # If neither security feature is enabled, don't register the handler.
    if not (dangerous_enabled or sandboxing_enabled):
        return

    from src.core.services.unified_tool_security_handler import (
        UnifiedToolSecurityHandler,
    )

    def unified_security_handler_factory(
        provider: IServiceProvider,
    ) -> UnifiedToolSecurityHandler:
        """Factory for creating UnifiedToolSecurityHandler."""
        from src.core.domain.configuration.unified_security_config import (
            UnifiedSecurityConfig,
        )
        from src.core.interfaces.session_service_interface import ISessionService

        # Get dependencies
        config = provider.get_service(AppConfig) or app_config
        path_validator = provider.get_service(cast(type, IPathValidator))
        session_service = provider.get_service(cast(type, ISessionService))

        raw_unified_security = getattr(config, "unified_security", None)
        if raw_unified_security is not None:
            unified_security_config = UnifiedSecurityConfig.model_validate(
                raw_unified_security
            )
        else:
            dangerous_command_config = getattr(config, "dangerous_commands", None)
            unified_security_config = UnifiedSecurityConfig.from_legacy_configs(
                dangerous_command_config,
                config.sandboxing,
            )

        dangerous_command_prevention_enabled = getattr(
            config.session, "dangerous_command_prevention_enabled", True
        )
        unified_security_config.dangerous_commands.enabled = (
            dangerous_command_prevention_enabled
        )
        unified_security_config.file_sandboxing.enabled = getattr(
            config.sandboxing, "enabled", False
        )
        unified_security_config.enabled = (
            unified_security_config.is_any_feature_enabled()
        )

        return UnifiedToolSecurityHandler(
            config=unified_security_config,
            path_validator=path_validator,
            session_service=session_service,
        )

    register_singleton_if_absent(
        services,
        UnifiedToolSecurityHandler,
        implementation_factory=unified_security_handler_factory,
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered UnifiedToolSecurityHandler")
