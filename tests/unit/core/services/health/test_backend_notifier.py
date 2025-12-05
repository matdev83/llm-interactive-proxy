"""Tests for the BackendHealthNotifier service."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from src.core.domain.configuration.health_check_config import HealthCheckConfig
from src.core.domain.events.health_events import EndpointHealthChanged
from src.core.services.event_bus import EventBus
from src.core.services.health.backend_notifier import BackendHealthNotifier
from src.core.services.health.endpoint_registry import EndpointRegistry


class MockHealthAwareBackend:
    """Mock backend implementing IHealthAware."""

    def __init__(self, api_url: str | None = None) -> None:
        self._api_url = api_url
        self._endpoint_healthy = True
        self.on_endpoint_healthy = AsyncMock()
        self.on_endpoint_unhealthy = AsyncMock()

    @property
    def api_url(self) -> str | None:
        return self._api_url

    @property
    def is_endpoint_healthy(self) -> bool:
        return self._endpoint_healthy


class TestBackendHealthNotifier:
    """Tests for BackendHealthNotifier."""

    @pytest.fixture
    def event_bus(self) -> EventBus:
        """Create a fresh event bus."""
        return EventBus()

    @pytest.fixture
    def endpoint_registry(self) -> EndpointRegistry:
        """Create a fresh endpoint registry."""
        return EndpointRegistry()

    @pytest.fixture
    def config(self) -> HealthCheckConfig:
        """Create health check config with notifications enabled."""
        return HealthCheckConfig(notify_backends=True)

    @pytest.fixture
    def notifier(
        self,
        event_bus: EventBus,
        endpoint_registry: EndpointRegistry,
        config: HealthCheckConfig,
    ) -> BackendHealthNotifier:
        """Create a backend notifier."""
        return BackendHealthNotifier(
            event_bus=event_bus,
            endpoint_registry=endpoint_registry,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_register_backend(self, notifier: BackendHealthNotifier) -> None:
        """Test registering a backend for notifications."""
        backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")

        notifier.register_backend(backend)

        backends = notifier.get_backends_for_url("https://api.openai.com/v1")
        assert backend in backends

    @pytest.mark.asyncio
    async def test_register_backend_without_url(
        self, notifier: BackendHealthNotifier
    ) -> None:
        """Test that registering a backend without URL is a no-op."""
        backend = MockHealthAwareBackend(api_url=None)

        notifier.register_backend(backend)

        # Should not be registered anywhere
        assert len(notifier._backends) == 0

    @pytest.mark.asyncio
    async def test_unregister_backend(self, notifier: BackendHealthNotifier) -> None:
        """Test unregistering a backend."""
        backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")

        notifier.register_backend(backend)
        notifier.unregister_backend(backend)

        backends = notifier.get_backends_for_url("https://api.openai.com/v1")
        assert backend not in backends

    @pytest.mark.asyncio
    async def test_multiple_backends_same_url(
        self, notifier: BackendHealthNotifier
    ) -> None:
        """Test multiple backends registered for the same URL."""
        backend1 = MockHealthAwareBackend(api_url="https://api.openai.com/v1")
        backend2 = MockHealthAwareBackend(api_url="https://api.openai.com/v1")

        notifier.register_backend(backend1)
        notifier.register_backend(backend2)

        backends = notifier.get_backends_for_url("https://api.openai.com/v1")
        assert len(backends) == 2
        assert backend1 in backends
        assert backend2 in backends

    @pytest.mark.asyncio
    async def test_notify_on_endpoint_unhealthy_ping(
        self,
        event_bus: EventBus,
        notifier: BackendHealthNotifier,
    ) -> None:
        """Test that backends are notified when endpoint becomes unhealthy (ping)."""
        await notifier.start()

        backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")
        notifier.register_backend(backend)

        # Publish endpoint health changed to unhealthy (ping failed)
        event = EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=False,
            ping_healthy=False,
            http_healthy=True,
        )
        await event_bus.publish(event)

        # Backend should have been notified
        backend.on_endpoint_unhealthy.assert_called_once()
        call_args = backend.on_endpoint_unhealthy.call_args
        assert call_args[0][0] == "https://api.openai.com/v1"

    @pytest.mark.asyncio
    async def test_notify_on_endpoint_healthy_recovery(
        self,
        event_bus: EventBus,
        notifier: BackendHealthNotifier,
    ) -> None:
        """Test that backends are notified on health recovery."""
        await notifier.start()

        backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")
        notifier.register_backend(backend)

        # Publish endpoint health changed to healthy
        event = EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=True,
            ping_healthy=True,
            http_healthy=True,
        )
        await event_bus.publish(event)

        # Backend should have been notified of recovery
        backend.on_endpoint_healthy.assert_called_once()
        call_args = backend.on_endpoint_healthy.call_args
        assert call_args[0][0] == "https://api.openai.com/v1"

    @pytest.mark.asyncio
    async def test_notify_on_endpoint_unhealthy_http(
        self,
        event_bus: EventBus,
        notifier: BackendHealthNotifier,
    ) -> None:
        """Test that backends are notified when endpoint becomes unhealthy (HTTP)."""
        await notifier.start()

        backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")
        notifier.register_backend(backend)

        # Publish endpoint health changed to unhealthy (HTTP failed)
        event = EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=False,
            ping_healthy=True,
            http_healthy=False,
        )
        await event_bus.publish(event)

        # Backend should have been notified
        backend.on_endpoint_unhealthy.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_on_combined_failures(
        self,
        event_bus: EventBus,
        notifier: BackendHealthNotifier,
    ) -> None:
        """Test that backends are notified when both ping and HTTP fail."""
        await notifier.start()

        backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")
        notifier.register_backend(backend)

        # Publish combined health failure
        event = EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=False,
            ping_healthy=False,
            http_healthy=False,
        )
        await event_bus.publish(event)

        # Backend should have been notified
        backend.on_endpoint_unhealthy.assert_called_once()
        # Reason should include both failures
        call_args = backend.on_endpoint_unhealthy.call_args
        reason = call_args[0][1]
        assert "ping" in reason.lower()
        assert "http" in reason.lower()

    @pytest.mark.asyncio
    async def test_only_affected_backends_notified(
        self,
        event_bus: EventBus,
        notifier: BackendHealthNotifier,
    ) -> None:
        """Test that only backends for the affected URL are notified."""
        await notifier.start()

        openai_backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")
        anthropic_backend = MockHealthAwareBackend(
            api_url="https://api.anthropic.com/v1"
        )

        notifier.register_backend(openai_backend)
        notifier.register_backend(anthropic_backend)

        # Publish event for OpenAI URL only
        event = EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=False,
            ping_healthy=False,
            http_healthy=True,
        )
        await event_bus.publish(event)

        # Only OpenAI backend should be notified
        openai_backend.on_endpoint_unhealthy.assert_called_once()
        anthropic_backend.on_endpoint_unhealthy.assert_not_called()

    @pytest.mark.asyncio
    async def test_notifier_disabled_by_config(
        self,
        event_bus: EventBus,
        endpoint_registry: EndpointRegistry,
    ) -> None:
        """Test that notifier does not subscribe when disabled by config."""
        config = HealthCheckConfig(notify_backends=False)
        notifier = BackendHealthNotifier(
            event_bus=event_bus,
            endpoint_registry=endpoint_registry,
            config=config,
        )

        await notifier.start()

        # Should not have subscribed to events
        assert not event_bus.has_subscribers(EndpointHealthChanged)

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(
        self,
        event_bus: EventBus,
        notifier: BackendHealthNotifier,
    ) -> None:
        """Test that stop() unsubscribes from events."""
        await notifier.start()

        # Should have subscribers
        assert event_bus.has_subscribers(EndpointHealthChanged)

        await notifier.stop()

        # Should no longer have subscribers
        assert not event_bus.has_subscribers(EndpointHealthChanged)

    @pytest.mark.asyncio
    async def test_url_normalization(self, notifier: BackendHealthNotifier) -> None:
        """Test that URL normalization is applied when looking up backends."""
        # Register with trailing slash
        backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1/")
        notifier.register_backend(backend)

        # Look up without trailing slash
        backends = notifier.get_backends_for_url("https://api.openai.com/v1")
        assert backend in backends

    @pytest.mark.asyncio
    async def test_handler_error_does_not_affect_other_backends(
        self,
        event_bus: EventBus,
        notifier: BackendHealthNotifier,
    ) -> None:
        """Test that an error in one backend handler doesn't affect others."""
        await notifier.start()

        # Create one backend that raises, one that doesn't
        error_backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")
        error_backend.on_endpoint_unhealthy = AsyncMock(
            side_effect=RuntimeError("Backend error")
        )

        good_backend = MockHealthAwareBackend(api_url="https://api.openai.com/v1")

        notifier.register_backend(error_backend)
        notifier.register_backend(good_backend)

        # Publish event - should not raise
        event = EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=False,
            ping_healthy=False,
            http_healthy=True,
        )
        await event_bus.publish(event)

        # Good backend should still have been notified
        good_backend.on_endpoint_unhealthy.assert_called_once()
