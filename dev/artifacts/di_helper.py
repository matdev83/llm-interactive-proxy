"""
Helper utilities for debug scripts to use DI-managed services.

This module provides helper functions to create minimal DI containers
for debug/reproduction scripts that need to instantiate services.
"""

from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registration_helpers.core_foundational import (
    register_application_state_services,
)
from src.core.di.registrations import streaming, tooling
from src.core.interfaces.streaming_response_processor_interface import (
    IStreamNormalizer,
)
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.tool_call_repair_service import ToolCallRepairService
from src.core.services.translation_service import TranslationService


def create_minimal_service_provider() -> ServiceCollection:
    """
    Create a minimal service provider with core services for debug scripts.

    Returns:
        ServiceCollection configured with minimal services
    """
    services = ServiceCollection()
    config = AppConfig()
    services.add_instance(AppConfig, config)

    # Register core foundational services (includes ToolCallRepairService)
    register_application_state_services(services)

    # Register streaming services (includes StreamNormalizer)
    streaming.register(services, config)

    # Register tooling services
    tooling.register(services, config)

    # Register TranslationService
    services.add_singleton(TranslationService)

    return services


def get_tool_call_repair_service() -> ToolCallRepairService:
    """
    Get ToolCallRepairService instance via DI for debug scripts.

    Returns:
        ToolCallRepairService instance
    """
    services = create_minimal_service_provider()
    provider = services.build_service_provider()
    service = provider.get_required_service(IToolCallRepairService)  # type: ignore[type-abstract]
    return cast(ToolCallRepairService, service)


def get_translation_service() -> TranslationService:
    """
    Get TranslationService instance via DI for debug scripts.

    Returns:
        TranslationService instance
    """
    services = create_minimal_service_provider()
    provider = services.build_service_provider()
    return provider.get_required_service(TranslationService)


def get_stream_normalizer() -> StreamNormalizer:
    """
    Get StreamNormalizer instance via DI for debug scripts.

    Returns:
        StreamNormalizer instance
    """
    services = create_minimal_service_provider()
    provider = services.build_service_provider()
    service = provider.get_required_service(IStreamNormalizer)  # type: ignore[type-abstract]
    return cast(StreamNormalizer, service)


def get_response_processor() -> ResponseProcessor:
    """
    Get ResponseProcessor instance via DI for debug scripts.

    Returns:
        ResponseProcessor instance
    """
    services = create_minimal_service_provider()
    provider = services.build_service_provider()
    from src.core.interfaces.response_processor_interface import IResponseProcessor

    service = provider.get_required_service(IResponseProcessor)  # type: ignore[type-abstract]
    return cast(ResponseProcessor, service)
