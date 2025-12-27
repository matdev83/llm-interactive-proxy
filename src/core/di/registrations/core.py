"""
Core services registrar.

Registers foundational services: configuration, session management, application state,
command pipeline, and request processing orchestration.
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registration_helpers.core_commands import (
    register_command_pipeline_services,
)
from src.core.di.registration_helpers.core_foundational import (
    register_app_config,
    register_application_state_services,
    register_session_services,
    register_time_source,
)
from src.core.di.registration_helpers.core_processing import (
    register_phase_components,
    register_request_processing_orchestration,
)

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register core services.

    This registrar handles:
    - AppConfig and IConfig
    - Time source (TimeSource, ITimeSource)
    - Session services (SessionService, SessionResolver)
    - Application state (ApplicationStateService, AppSettings, SecureStateService)
    - Command pipeline (CommandService, CommandParser, CommandProcessor, CommandStateService, CommandPolicyService)
    - Request processing orchestration (RequestProcessor, BackendProcessor, BackendRequestManager)
    - Phase components (SessionEnricher, RequestSideEffects, CommandHandler, BackendPreparer, RequestTransformPipeline, BackendExecutor)
    - Response handlers and managers
    - Middleware and loop detection

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # Register AppConfig and IConfig
    register_app_config(services, app_config)

    # Register time source (early, as other services may depend on it)
    register_time_source(services)

    # Register foundational services
    register_session_services(services)
    register_application_state_services(services)
    register_command_pipeline_services(services)

    # Register request processing orchestration
    register_request_processing_orchestration(services)

    # Register phase components
    register_phase_components(services)
