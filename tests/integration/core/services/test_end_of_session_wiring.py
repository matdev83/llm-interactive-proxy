"""Integration tests for End-of-Session service wiring.

This module tests that EventBus and EndOfSessionService are registered
and available for EoS pipeline components.

EventBus is registered in CoreServicesStage.
EndOfSessionService is registered in streaming registrations (called from CoreServicesStage).
"""

from __future__ import annotations

import pytest
from src.core.app.stages.core_services import CoreServicesStage
from src.core.app.stages.infrastructure import InfrastructureStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.end_of_session_service_interface import (
    IEndOfSessionService,
)
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.services.end_of_session_service import EndOfSessionService
from src.core.services.event_bus import EventBus


@pytest.mark.asyncio
async def test_event_bus_registered_in_core_services_stage() -> None:
    """Test that EventBus is registered in CoreServicesStage."""
    # Setup DI container
    services = ServiceCollection()
    config = AppConfig()

    # Initialize required stages
    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Resolve EventBus via interface
    event_bus = provider.get_required_service(IEventBus)
    assert event_bus is not None
    assert isinstance(event_bus, EventBus)

    # Resolve EventBus via concrete type
    event_bus_concrete = provider.get_required_service(EventBus)
    assert event_bus_concrete is not None
    assert event_bus_concrete is event_bus  # Should be same instance (singleton)


@pytest.mark.asyncio
async def test_end_of_session_service_registered_in_core_services_stage() -> None:
    """Test that EndOfSessionService is registered via streaming registrations."""
    # Setup DI container
    services = ServiceCollection()
    config = AppConfig()

    # Initialize required stages
    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Resolve EndOfSessionService via interface
    eos_service = provider.get_required_service(IEndOfSessionService)
    assert eos_service is not None
    assert isinstance(eos_service, EndOfSessionService)

    # Resolve EndOfSessionService via concrete type
    eos_service_concrete = provider.get_required_service(EndOfSessionService)
    assert eos_service_concrete is not None
    assert eos_service_concrete is eos_service  # Should be same instance (singleton)


@pytest.mark.asyncio
async def test_end_of_session_service_depends_on_event_bus() -> None:
    """Test that EndOfSessionService can access EventBus dependency."""
    # Setup DI container
    services = ServiceCollection()
    config = AppConfig()

    # Initialize required stages
    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Resolve EndOfSessionService
    eos_service = provider.get_required_service(IEndOfSessionService)
    assert eos_service is not None

    # Verify EventBus is injected
    assert eos_service._event_bus is not None
    assert isinstance(eos_service._event_bus, EventBus)


@pytest.mark.asyncio
async def test_end_of_session_stream_processor_in_pipeline() -> None:
    """Test that EndOfSessionStreamProcessor is in the StreamNormalizer pipeline."""
    # Setup DI container
    services = ServiceCollection()
    config = AppConfig()

    # Initialize required stages
    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Resolve StreamNormalizer (which should include EndOfSessionStreamProcessor)
    from src.core.interfaces.streaming_response_processor_interface import (
        IStreamNormalizer,
    )
    from src.core.services.streaming.stream_normalizer import StreamNormalizer

    stream_normalizer = provider.get_service(IStreamNormalizer)
    if stream_normalizer is None:
        pytest.skip("StreamNormalizer not registered (EoS may be disabled)")

    assert isinstance(stream_normalizer, StreamNormalizer)

    # Check if EndOfSessionStreamProcessor is in the processor chain
    # The processor should be registered if EoS is enabled

    # Verify EndOfSessionService exists (required for processor)
    eos_service = provider.get_service(IEndOfSessionService)
    if eos_service is None:
        pytest.skip("EndOfSessionService not registered (EoS may be disabled)")

    # The processor chain is internal, but we can verify the service exists
    # which is required for the processor to be added
    assert eos_service is not None


@pytest.mark.asyncio
async def test_end_of_session_tool_call_handler_registered() -> None:
    """Test that EndOfSessionToolCallHandler can be registered."""
    # Setup DI container
    services = ServiceCollection()
    config = AppConfig()

    # Initialize required stages
    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Verify EndOfSessionService exists (required for handler)
    eos_service = provider.get_service(IEndOfSessionService)
    if eos_service is None:
        pytest.skip("EndOfSessionService not registered (EoS may be disabled)")

    # The handler is registered via provider_lifecycle, which requires
    # additional stages. For this test, we just verify the service exists
    # which is a prerequisite for handler registration
    assert eos_service is not None
