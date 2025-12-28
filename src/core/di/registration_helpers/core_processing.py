"""
Core request processing registration helper.

Registers:
- Request processing orchestration (RequestProcessor, BackendProcessor, BackendRequestManager)
- Phase components (SessionEnricher, RequestSideEffects, CommandHandler, BackendPreparer, RequestTransformPipeline, BackendExecutor)
"""

from __future__ import annotations

import logging

from src.core.di.container import ServiceCollection
from src.core.di.registration_helpers.request_processing._rp_backend_components import (
    register_backend_component_services,
)
from src.core.di.registration_helpers.request_processing._rp_orchestration_core import (
    register_orchestration_core_services,
)
from src.core.di.registration_helpers.request_processing._rp_phase_components import (
    register_request_phase_components,
)

logger = logging.getLogger(__name__)


def register_request_processing_orchestration(services: ServiceCollection) -> None:
    """Register request processing orchestration services.

    CRITICAL: This function is called by core.py registrar and MUST preserve
    exact registration order for compatibility.
    """
    # Order matters - core services first, then components
    register_orchestration_core_services(services)
    register_backend_component_services(services)


def register_phase_components(services: ServiceCollection) -> None:
    """Register request processor phase components.

    CRITICAL: This function is called by core.py registrar and MUST preserve
    exact registration order for compatibility.
    """
    register_request_phase_components(services)
