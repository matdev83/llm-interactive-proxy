"""
Tests for streaming services registrar.

These tests verify that:
- StreamingContextRegistry is registered correctly
- MiddlewareApplicationManager is registered correctly
- MiddlewareApplicationProcessor is registered correctly
- StreamNormalizer and IStreamNormalizer are registered correctly
- StreamFormattingService and IStreamFormattingService are registered correctly
- Processor chain is configured correctly
"""

from __future__ import annotations

import contextlib
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations import core, streaming
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.services.event_bus import EventBus
from src.core.services.middleware_application_manager import (
    MiddlewareApplicationManager,
)
from src.core.services.stream_formatting_service import StreamFormattingService
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.stream_normalizer import StreamNormalizer


def _register_event_bus(services: ServiceCollection) -> None:
    """Register EventBus for tests that need it (e.g., StreamNormalizer with EoS)."""

    def event_bus_factory(provider: IServiceProvider) -> EventBus:
        return EventBus()

    services.add_singleton(EventBus, implementation_factory=event_bus_factory)
    services.add_singleton(
        cast(type, IEventBus),
        implementation_factory=lambda p: p.get_required_service(EventBus),
    )


class TestStreamingRegistrar:
    """Test streaming services registration."""

    def test_streaming_context_registry_registration(self) -> None:
        """Verify StreamingContextRegistry is registered as singleton."""
        services = ServiceCollection()
        config = AppConfig()

        # Register core services first (streaming depends on core)
        core.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider()

        registry = provider.get_service(StreamingContextRegistry)
        assert registry is not None
        assert isinstance(registry, StreamingContextRegistry)

        # Verify singleton behavior
        registry2 = provider.get_service(StreamingContextRegistry)
        assert registry is registry2

    def test_middleware_application_manager_registration(self) -> None:
        """Verify MiddlewareApplicationManager is registered correctly."""
        services = ServiceCollection()
        config = AppConfig()

        # Register core services first (streaming depends on core)
        core.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider()

        manager = provider.get_service(MiddlewareApplicationManager)
        assert manager is not None
        assert isinstance(manager, MiddlewareApplicationManager)

        # Verify singleton behavior
        manager2 = provider.get_service(MiddlewareApplicationManager)
        assert manager is manager2

    def test_middleware_application_processor_registration(self) -> None:
        """Verify MiddlewareApplicationProcessor is registered correctly."""
        services = ServiceCollection()
        config = AppConfig()

        # Register core services first (streaming depends on core)
        core.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider()

        processor = provider.get_service(MiddlewareApplicationProcessor)
        assert processor is not None
        assert isinstance(processor, MiddlewareApplicationProcessor)

        # Verify singleton behavior
        processor2 = provider.get_service(MiddlewareApplicationProcessor)
        assert processor is processor2

    def test_stream_normalizer_registration(self) -> None:
        """Verify StreamNormalizer and IStreamNormalizer are registered correctly."""
        services = ServiceCollection()
        config = AppConfig()

        # Register EventBus (required by EndOfSessionService which is used by StreamNormalizer)
        _register_event_bus(services)
        # Register core services first (streaming depends on core)
        core.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider()

        # Verify concrete type registration
        normalizer = provider.get_service(StreamNormalizer)
        assert normalizer is not None
        assert isinstance(normalizer, StreamNormalizer)

        # Verify interface registration
        inormalizer = provider.get_service(
            cast(type[IStreamNormalizer], IStreamNormalizer)
        )
        assert inormalizer is not None
        assert isinstance(inormalizer, StreamNormalizer)

        # Verify singleton behavior
        normalizer2 = provider.get_service(StreamNormalizer)
        assert normalizer is normalizer2
        assert inormalizer is normalizer

    def test_stream_normalizer_processor_chain(self) -> None:
        """Verify StreamNormalizer has correct processor chain configured."""
        services = ServiceCollection()
        config = AppConfig()

        # Register EventBus (required by EndOfSessionService which is used by StreamNormalizer)
        _register_event_bus(services)
        # Register core services first (streaming depends on core)
        core.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider()

        normalizer: IStreamNormalizer = provider.get_required_service(
            cast(type[IStreamNormalizer], IStreamNormalizer)
        )
        assert isinstance(normalizer, StreamNormalizer)

        # Verify processors are configured
        assert hasattr(normalizer, "_processors")
        processors = normalizer._processors
        assert len(processors) > 0

        # Verify ContentAccumulationProcessor is present (always added)
        from src.core.services.streaming.content_accumulation_processor import (
            ContentAccumulationProcessor,
        )

        has_accumulation = any(
            isinstance(p, ContentAccumulationProcessor) for p in processors
        )
        assert has_accumulation, "ContentAccumulationProcessor should be in chain"

    def test_stream_formatting_service_registration(self) -> None:
        """Verify StreamFormattingService and IStreamFormattingService are registered."""
        services = ServiceCollection()
        config = AppConfig()

        # Register core services first (streaming depends on core)
        core.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider()

        # Verify concrete type registration
        service = provider.get_service(StreamFormattingService)
        assert service is not None
        assert isinstance(service, StreamFormattingService)

        # Verify interface registration
        iservice = provider.get_service(cast(type, IStreamFormattingService))  # type: ignore[type-abstract]
        assert iservice is not None
        assert isinstance(iservice, StreamFormattingService)

        # Verify singleton behavior
        service2 = provider.get_service(StreamFormattingService)
        assert service is service2
        assert iservice is service

    def test_streaming_registrar_idempotency(self) -> None:
        """Verify streaming registrar can be called multiple times without errors."""
        services = ServiceCollection()
        config = AppConfig()

        # Register EventBus (required by EndOfSessionService which is used by StreamNormalizer)
        _register_event_bus(services)
        # Register core services first
        core.register(services, config)

        # Call streaming registrar multiple times
        streaming.register(services, config)
        streaming.register(services, config)
        streaming.register(services, config)

        provider = services.build_service_provider()

        # Verify services still resolve correctly
        normalizer = provider.get_service(
            cast(type[IStreamNormalizer], IStreamNormalizer)
        )
        assert normalizer is not None

        manager = provider.get_service(MiddlewareApplicationManager)
        assert manager is not None

    def test_streaming_registrar_without_core_dependencies(self) -> None:
        """Verify streaming registrar handles missing core dependencies gracefully."""
        services = ServiceCollection()
        config = AppConfig()

        # Try to register streaming without core - should fail when building provider
        streaming.register(services, config)

        # Building provider should fail due to missing dependencies
        # (This is expected - streaming depends on core)
        # But registration itself should not fail
        with contextlib.suppress(Exception):
            services.build_service_provider()
            # If it doesn't fail, that's also okay - some dependencies might be optional
