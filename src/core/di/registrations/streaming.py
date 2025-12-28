"""
Streaming pipeline registrar.

Registers streaming response processors, middleware, and response handling services.
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._streaming_pipeline import (
    register_streaming_pipeline_services,
)
from src.core.di.registrations._streaming_response import (
    register_response_processing_services,
)
from src.core.di.registrations._streaming_session_lifecycle import (
    register_session_lifecycle_services,
)

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register streaming pipeline services.

    This registrar handles:
    - EndOfSessionService and IEndOfSessionService
    - StreamingContextRegistry
    - MiddlewareApplicationManager
    - MiddlewareApplicationProcessor
    - StreamNormalizer and IProcessingStreamNormalizer
    - StreamFormattingService and IStreamFormattingService
    - Session cancellation and lifecycle services

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # CRITICAL: Preserve exact registration order for determinism

    # 1. Session lifecycle (must be before StreamNormalizer)
    register_session_lifecycle_services(services, app_config)

    # 2. Streaming pipeline core
    register_streaming_pipeline_services(services, app_config)

    # 3. Response processing
    register_response_processing_services(services)
