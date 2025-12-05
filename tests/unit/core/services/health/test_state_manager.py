"""Tests for the HealthStateManager class."""

from __future__ import annotations

import pytest
from src.core.domain.configuration.health_check_config import HealthCheckConfig
from src.core.domain.events.health_events import (
    HttpCheckFailed,
    HttpCheckSucceeded,
    HttpHealthStateTransition,
    PingCheckFailed,
    PingCheckSucceeded,
    PingHealthStateTransition,
)
from src.core.services.event_bus import EventBus
from src.core.services.health.endpoint_registry import EndpointRegistry
from src.core.services.health.state_manager import HealthStateManager


class TestHealthStateManager:
    """Tests for HealthStateManager."""

    @pytest.fixture
    def event_bus(self) -> EventBus:
        """Create event bus for testing."""
        return EventBus()

    @pytest.fixture
    def registry(self) -> EndpointRegistry:
        """Create endpoint registry for testing."""
        return EndpointRegistry()

    @pytest.fixture
    def config(self) -> HealthCheckConfig:
        """Create health check config for testing."""
        return HealthCheckConfig()

    @pytest.fixture
    def state_manager(
        self,
        event_bus: EventBus,
        registry: EndpointRegistry,
        config: HealthCheckConfig,
    ) -> HealthStateManager:
        """Create state manager for testing."""
        return HealthStateManager(
            event_bus=event_bus,
            endpoint_registry=registry,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_start_subscribes_to_events(
        self,
        state_manager: HealthStateManager,
        event_bus: EventBus,
    ) -> None:
        """Test that start() subscribes to check events."""
        await state_manager.start()

        assert event_bus.has_subscribers(PingCheckSucceeded)
        assert event_bus.has_subscribers(PingCheckFailed)
        assert event_bus.has_subscribers(HttpCheckSucceeded)
        assert event_bus.has_subscribers(HttpCheckFailed)

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_from_events(
        self,
        state_manager: HealthStateManager,
        event_bus: EventBus,
    ) -> None:
        """Test that stop() unsubscribes from check events."""
        await state_manager.start()
        await state_manager.stop()

        assert not event_bus.has_subscribers(PingCheckSucceeded)
        assert not event_bus.has_subscribers(PingCheckFailed)
        assert not event_bus.has_subscribers(HttpCheckSucceeded)
        assert not event_bus.has_subscribers(HttpCheckFailed)

    @pytest.mark.asyncio
    async def test_ping_success_updates_state(
        self,
        state_manager: HealthStateManager,
        event_bus: EventBus,
        registry: EndpointRegistry,
    ) -> None:
        """Test that ping success updates health state."""
        # Register endpoint
        api_url = "https://api.openai.com/v1"
        registry.register_backend("openai.1", api_url)

        await state_manager.start()

        # Publish ping success
        event = PingCheckSucceeded(api_url=api_url, latency_ms=50.0)
        await event_bus.publish(event)

        # Check state was updated
        state = registry.get_health_state(api_url)
        assert state is not None
        assert state.last_ping_latency_ms == 50.0

    @pytest.mark.asyncio
    async def test_ping_failure_emits_transition_event(
        self,
        state_manager: HealthStateManager,
        event_bus: EventBus,
        registry: EndpointRegistry,
        config: HealthCheckConfig,
    ) -> None:
        """Test that enough ping failures emit a transition event."""
        api_url = "https://api.openai.com/v1"
        registry.register_backend("openai.1", api_url)

        transitions: list[PingHealthStateTransition] = []

        async def capture_transition(event: PingHealthStateTransition) -> None:
            transitions.append(event)

        event_bus.subscribe(PingHealthStateTransition, capture_transition)
        await state_manager.start()

        # Send failures to reach threshold
        threshold = config.ping.failure_threshold
        for _ in range(threshold):
            event = PingCheckFailed(api_url=api_url, error="timeout")
            await event_bus.publish(event)

        # Should have one transition event
        assert len(transitions) == 1
        assert transitions[0].api_url == api_url
        assert transitions[0].old_state is True
        assert transitions[0].new_state is False

    @pytest.mark.asyncio
    async def test_http_success_updates_state(
        self,
        state_manager: HealthStateManager,
        event_bus: EventBus,
        registry: EndpointRegistry,
    ) -> None:
        """Test that HTTP success updates health state."""
        api_url = "https://api.openai.com/v1"
        registry.register_backend("openai.1", api_url)

        await state_manager.start()

        event = HttpCheckSucceeded(api_url=api_url, status_code=200, latency_ms=100.0)
        await event_bus.publish(event)

        state = registry.get_health_state(api_url)
        assert state is not None
        assert state.last_http_latency_ms == 100.0
        assert state.last_http_status_code == 200

    @pytest.mark.asyncio
    async def test_http_failure_emits_transition_event(
        self,
        state_manager: HealthStateManager,
        event_bus: EventBus,
        registry: EndpointRegistry,
        config: HealthCheckConfig,
    ) -> None:
        """Test that enough HTTP failures emit a transition event."""
        api_url = "https://api.openai.com/v1"
        registry.register_backend("openai.1", api_url)

        transitions: list[HttpHealthStateTransition] = []

        async def capture_transition(event: HttpHealthStateTransition) -> None:
            transitions.append(event)

        event_bus.subscribe(HttpHealthStateTransition, capture_transition)
        await state_manager.start()

        threshold = config.http.failure_threshold
        for _ in range(threshold):
            event = HttpCheckFailed(api_url=api_url, error="connection error")
            await event_bus.publish(event)

        assert len(transitions) == 1
        assert transitions[0].api_url == api_url
        assert transitions[0].old_state is True
        assert transitions[0].new_state is False

    @pytest.mark.asyncio
    async def test_recovery_emits_transition_event(
        self,
        state_manager: HealthStateManager,
        event_bus: EventBus,
        registry: EndpointRegistry,
        config: HealthCheckConfig,
    ) -> None:
        """Test that recovery from unhealthy emits a transition event."""
        api_url = "https://api.openai.com/v1"
        registry.register_backend("openai.1", api_url)

        transitions: list[HttpHealthStateTransition] = []

        async def capture_transition(event: HttpHealthStateTransition) -> None:
            transitions.append(event)

        event_bus.subscribe(HttpHealthStateTransition, capture_transition)
        await state_manager.start()

        # First, make it unhealthy
        threshold = config.http.failure_threshold
        for _ in range(threshold):
            event = HttpCheckFailed(api_url=api_url, error="error")
            await event_bus.publish(event)

        assert len(transitions) == 1
        assert transitions[0].new_state is False

        # Now recover
        event = HttpCheckSucceeded(api_url=api_url, status_code=200, latency_ms=50.0)
        await event_bus.publish(event)

        # Should have recovery transition
        assert len(transitions) == 2
        assert transitions[1].old_state is False
        assert transitions[1].new_state is True

    @pytest.mark.asyncio
    async def test_ignores_unregistered_urls(
        self,
        state_manager: HealthStateManager,
        event_bus: EventBus,
    ) -> None:
        """Test that events for unregistered URLs are ignored."""
        await state_manager.start()

        # Publish event for unregistered URL - should not raise
        event = PingCheckSucceeded(api_url="https://unknown.com", latency_ms=50.0)
        await event_bus.publish(event)  # Should not raise
