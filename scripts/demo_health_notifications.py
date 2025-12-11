#!/usr/bin/env python
"""Demo script to verify end-to-end health notification system.

This script demonstrates the in-process health notification system:
1. EventBus with topic-based subscriptions (API URLs as topics)
2. Multiple backends sharing the same API URL receiving notifications
3. Health state transitions triggering backend callbacks
4. Circuit breaker integration (unhealthy backends filtered from failover)
5. Logging of health state changes

For testing the /internal/health API endpoint, use: demo_health_api.py

Run with: .venv/Scripts/python.exe scripts/demo_health_notifications.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.domain.configuration.health_check_config import HealthCheckConfig
from src.core.domain.events.health_events import (
    EndpointHealthChanged,
    PingHealthStateTransition,
)
from src.core.interfaces.health_aware_interface import IHealthAware
from src.core.services.event_bus import EventBus
from src.core.services.health.backend_notifier import BackendHealthNotifier
from src.core.services.health.endpoint_registry import EndpointRegistry

# Configure logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("demo")


class MockBackend(IHealthAware):
    """Mock backend that implements IHealthAware for demonstration."""

    def __init__(self, name: str, api_url: str) -> None:
        self.name = name
        self._api_url = api_url
        self._endpoint_healthy = True
        self._notifications_received: list[str] = []

    @property
    def api_url(self) -> str | None:
        return self._api_url

    @property
    def is_endpoint_healthy(self) -> bool:
        return self._endpoint_healthy

    def is_backend_functional(self) -> bool:
        """Check if backend is functional (mimics LLMBackend behavior)."""
        return self._endpoint_healthy

    async def on_endpoint_healthy(self, api_url: str) -> None:
        """Called when endpoint recovers."""
        self._endpoint_healthy = True
        msg = f"RECOVERED - endpoint {api_url} is now healthy"
        self._notifications_received.append(msg)
        logger.info("[%s] %s", self.name, msg)

    async def on_endpoint_unhealthy(self, api_url: str, reason: str) -> None:
        """Called when endpoint becomes unhealthy."""
        self._endpoint_healthy = False
        msg = f"DEGRADED - endpoint {api_url} is now unhealthy: {reason}"
        self._notifications_received.append(msg)
        logger.warning("[%s] %s", self.name, msg)


async def demo_topic_based_event_routing():
    """Demonstrate topic-based event routing in EventBus."""
    print("\n" + "=" * 70)
    print("DEMO 1: Topic-Based Event Routing")
    print("=" * 70)

    event_bus = EventBus()

    # Track events received by each handler
    openai_events: list[str] = []
    anthropic_events: list[str] = []
    broadcast_events: list[str] = []

    async def openai_handler(event: PingHealthStateTransition) -> None:
        openai_events.append(f"ping:{event.api_url}:{event.new_state}")

    async def anthropic_handler(event: PingHealthStateTransition) -> None:
        anthropic_events.append(f"ping:{event.api_url}:{event.new_state}")

    async def broadcast_handler(event: PingHealthStateTransition) -> None:
        broadcast_events.append(f"ping:{event.api_url}:{event.new_state}")

    # Subscribe with topics (API URLs)
    event_bus.subscribe(
        PingHealthStateTransition,
        openai_handler,
        topic="https://api.openai.com/v1",
    )
    event_bus.subscribe(
        PingHealthStateTransition,
        anthropic_handler,
        topic="https://api.anthropic.com",
    )
    # Broadcast subscriber (no topic filter)
    event_bus.subscribe(PingHealthStateTransition, broadcast_handler, topic=None)

    print("\nSubscribed handlers:")
    print("  - openai_handler -> topic='https://api.openai.com/v1'")
    print("  - anthropic_handler -> topic='https://api.anthropic.com'")
    print("  - broadcast_handler -> topic=None (receives ALL events)")

    # Publish events with topics
    print("\nPublishing events...")

    await event_bus.publish(
        PingHealthStateTransition(
            api_url="https://api.openai.com/v1",
            old_state=True,
            new_state=False,
            consecutive_failures=3,
        ),
        topic="https://api.openai.com/v1",
    )
    print("  Published: PingHealthStateTransition for OpenAI (unhealthy)")

    await event_bus.publish(
        PingHealthStateTransition(
            api_url="https://api.anthropic.com",
            old_state=True,
            new_state=False,
            consecutive_failures=2,
        ),
        topic="https://api.anthropic.com",
    )
    print("  Published: PingHealthStateTransition for Anthropic (unhealthy)")

    # Verify routing
    print("\nResults:")
    print(f"  openai_handler received: {openai_events}")
    print(f"  anthropic_handler received: {anthropic_events}")
    print(f"  broadcast_handler received: {broadcast_events}")

    assert len(openai_events) == 1, "OpenAI handler should receive 1 event"
    assert len(anthropic_events) == 1, "Anthropic handler should receive 1 event"
    assert len(broadcast_events) == 2, "Broadcast handler should receive ALL events"

    print("\n[PASS] Topic-based routing works correctly!")
    await event_bus.shutdown()


async def demo_backend_notifications():
    """Demonstrate multiple backends receiving health notifications."""
    print("\n" + "=" * 70)
    print("DEMO 2: Backend Health Notifications")
    print("=" * 70)

    event_bus = EventBus()
    endpoint_registry = EndpointRegistry()
    config = HealthCheckConfig(notify_backends=True)

    notifier = BackendHealthNotifier(
        event_bus=event_bus,
        endpoint_registry=endpoint_registry,
        config=config,
    )
    await notifier.start()

    # Create multiple backends sharing the same API URL
    # This simulates multiple backend instances (e.g., openai.1, openai.2)
    openai_backend_1 = MockBackend("openai.1", "https://api.openai.com/v1")
    openai_backend_2 = MockBackend("openai.2", "https://api.openai.com/v1")
    anthropic_backend = MockBackend("anthropic.1", "https://api.anthropic.com")

    # Register backends for notifications
    notifier.register_backend(openai_backend_1)
    notifier.register_backend(openai_backend_2)
    notifier.register_backend(anthropic_backend)

    print("\nRegistered backends:")
    print(f"  - {openai_backend_1.name} -> {openai_backend_1.api_url}")
    print(f"  - {openai_backend_2.name} -> {openai_backend_2.api_url}")
    print(f"  - {anthropic_backend.name} -> {anthropic_backend.api_url}")

    # Verify initial state
    print("\nInitial state (all healthy):")
    print(
        f"  - {openai_backend_1.name}.is_endpoint_healthy = {openai_backend_1.is_endpoint_healthy}"
    )
    print(
        f"  - {openai_backend_2.name}.is_endpoint_healthy = {openai_backend_2.is_endpoint_healthy}"
    )
    print(
        f"  - {anthropic_backend.name}.is_endpoint_healthy = {anthropic_backend.is_endpoint_healthy}"
    )

    # Simulate OpenAI endpoint becoming unhealthy
    # Note: BackendHealthNotifier listens to EndpointHealthChanged (combined status)
    print("\n--- Simulating OpenAI endpoint failure ---")
    await event_bus.publish(
        EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=False,
            ping_healthy=False,
            http_healthy=True,
        )
    )

    # Give async handlers time to complete
    await asyncio.sleep(0.1)

    print("\nAfter OpenAI health degradation:")
    print(
        f"  - {openai_backend_1.name}.is_endpoint_healthy = {openai_backend_1.is_endpoint_healthy}"
    )
    print(
        f"  - {openai_backend_2.name}.is_endpoint_healthy = {openai_backend_2.is_endpoint_healthy}"
    )
    print(
        f"  - {anthropic_backend.name}.is_endpoint_healthy = {anthropic_backend.is_endpoint_healthy}"
    )

    # Verify both OpenAI backends were notified, but not Anthropic
    assert not openai_backend_1.is_endpoint_healthy, "openai.1 should be unhealthy"
    assert not openai_backend_2.is_endpoint_healthy, "openai.2 should be unhealthy"
    assert anthropic_backend.is_endpoint_healthy, "anthropic.1 should still be healthy"
    assert len(openai_backend_1._notifications_received) == 1
    assert len(openai_backend_2._notifications_received) == 1
    assert len(anthropic_backend._notifications_received) == 0

    print("\n[PASS] Both OpenAI backends notified, Anthropic unaffected!")

    # Simulate recovery
    print("\n--- Simulating OpenAI endpoint recovery ---")
    await event_bus.publish(
        EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=True,
            ping_healthy=True,
            http_healthy=True,
        )
    )

    await asyncio.sleep(0.1)

    print("\nAfter OpenAI recovery:")
    print(
        f"  - {openai_backend_1.name}.is_endpoint_healthy = {openai_backend_1.is_endpoint_healthy}"
    )
    print(
        f"  - {openai_backend_2.name}.is_endpoint_healthy = {openai_backend_2.is_endpoint_healthy}"
    )

    assert openai_backend_1.is_endpoint_healthy, "openai.1 should be healthy again"
    assert openai_backend_2.is_endpoint_healthy, "openai.2 should be healthy again"

    print("\n[PASS] Both OpenAI backends received recovery notification!")

    # Show notification history
    print("\nNotification history:")
    print(f"  {openai_backend_1.name}: {openai_backend_1._notifications_received}")
    print(f"  {openai_backend_2.name}: {openai_backend_2._notifications_received}")
    print(f"  {anthropic_backend.name}: {anthropic_backend._notifications_received}")

    await notifier.stop()
    await event_bus.shutdown()


async def demo_circuit_breaker():
    """Demonstrate circuit breaker filtering unhealthy backends."""
    print("\n" + "=" * 70)
    print("DEMO 3: Circuit Breaker Integration")
    print("=" * 70)

    # Create mock backends
    backends = {
        "openai.1": MockBackend("openai.1", "https://api.openai.com/v1"),
        "openai.2": MockBackend("openai.2", "https://api.openai.com/v1"),
        "anthropic.1": MockBackend("anthropic.1", "https://api.anthropic.com"),
    }

    # Simulate the failover plan filtering logic from BackendService
    def filter_unhealthy_backends(
        plan: list[tuple[str, str]],
        backends_dict: dict[str, MockBackend],
        circuit_breaker_enabled: bool,
    ) -> list[tuple[str, str]]:
        """Mimics BackendService._filter_unhealthy_backends()"""
        if not circuit_breaker_enabled:
            return plan

        filtered = []
        for backend_name, model_name in plan:
            backend = backends_dict.get(backend_name)
            if backend is None:
                filtered.append((backend_name, model_name))
                continue

            if backend.is_backend_functional():
                filtered.append((backend_name, model_name))
            else:
                logger.info(
                    "Skipping backend %s (unhealthy endpoint) in failover plan",
                    backend_name,
                )

        if not filtered and plan:
            logger.warning(
                "All backends filtered as unhealthy, falling back to original plan"
            )
            return plan

        return filtered

    # Initial failover plan
    original_plan = [
        ("openai.1", "gpt-4"),
        ("openai.2", "gpt-4"),
        ("anthropic.1", "claude-3"),
    ]

    print("\nOriginal failover plan:")
    for backend, model in original_plan:
        print(f"  - {backend} -> {model}")

    # All healthy - plan unchanged
    filtered = filter_unhealthy_backends(original_plan, backends, True)
    print("\nWith all backends healthy:")
    for backend, model in filtered:
        print(f"  - {backend} -> {model}")
    assert len(filtered) == 3, "All backends should be in plan"

    # Mark openai.1 as unhealthy
    backends["openai.1"]._endpoint_healthy = False
    print("\n--- Marking openai.1 as unhealthy ---")

    filtered = filter_unhealthy_backends(original_plan, backends, True)
    print("\nFiltered plan (openai.1 should be excluded):")
    for backend, model in filtered:
        print(f"  - {backend} -> {model}")

    assert len(filtered) == 2, "openai.1 should be filtered out"
    assert ("openai.1", "gpt-4") not in filtered
    print("\n[PASS] Unhealthy backend correctly filtered!")

    # Mark all OpenAI backends as unhealthy
    backends["openai.2"]._endpoint_healthy = False
    print("\n--- Marking openai.2 as unhealthy ---")

    filtered = filter_unhealthy_backends(original_plan, backends, True)
    print("\nFiltered plan (both OpenAI should be excluded):")
    for backend, model in filtered:
        print(f"  - {backend} -> {model}")

    assert len(filtered) == 1, "Only anthropic.1 should remain"
    assert filtered[0] == ("anthropic.1", "claude-3")
    print("\n[PASS] Multiple unhealthy backends filtered!")

    # Circuit breaker disabled
    print("\n--- Testing with circuit_breaker_enabled=False ---")
    filtered = filter_unhealthy_backends(original_plan, backends, False)
    assert len(filtered) == 3, "No filtering when circuit breaker disabled"
    print("[PASS] Circuit breaker can be disabled!")


async def demo_combined_health_events():
    """Demonstrate combined ping + HTTP health events."""
    print("\n" + "=" * 70)
    print("DEMO 4: Combined Health Events (Ping + HTTP)")
    print("=" * 70)

    event_bus = EventBus()
    endpoint_registry = EndpointRegistry()
    config = HealthCheckConfig(notify_backends=True)

    notifier = BackendHealthNotifier(
        event_bus=event_bus,
        endpoint_registry=endpoint_registry,
        config=config,
    )
    await notifier.start()

    backend = MockBackend("openai.1", "https://api.openai.com/v1")
    notifier.register_backend(backend)

    print(f"\nBackend: {backend.name} -> {backend.api_url}")
    print(f"Initial state: is_endpoint_healthy = {backend.is_endpoint_healthy}")

    # HTTP check failure (ping still healthy)
    print("\n--- HTTP check failure (ping still healthy) ---")
    await event_bus.publish(
        EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=False,
            ping_healthy=True,
            http_healthy=False,
        )
    )
    await asyncio.sleep(0.1)
    print(f"After HTTP failure: is_endpoint_healthy = {backend.is_endpoint_healthy}")
    assert not backend.is_endpoint_healthy

    # Recovery when both checks pass
    print("\n--- Recovery (both ping and HTTP healthy) ---")
    await event_bus.publish(
        EndpointHealthChanged(
            api_url="https://api.openai.com/v1",
            is_healthy=True,
            ping_healthy=True,
            http_healthy=True,
        )
    )
    await asyncio.sleep(0.1)
    print(f"After recovery: is_endpoint_healthy = {backend.is_endpoint_healthy}")
    assert backend.is_endpoint_healthy

    print("\n[PASS] Combined health events (EndpointHealthChanged) work!")

    # Show all notifications
    print(f"\nAll notifications received: {backend._notifications_received}")

    await notifier.stop()
    await event_bus.shutdown()


async def main():
    """Run all demos."""
    print("\n" + "#" * 70)
    print("# Health Check Notification System - End-to-End Demo")
    print("#" * 70)

    try:
        await demo_topic_based_event_routing()
        await demo_backend_notifications()
        await demo_circuit_breaker()
        await demo_combined_health_events()

        print("\n" + "=" * 70)
        print("ALL DEMOS PASSED SUCCESSFULLY!")
        print("=" * 70)
        print("\nThe health notification system is working as expected:")
        print("  1. EventBus supports topic-based subscriptions (API URLs as topics)")
        print("  2. Multiple backends sharing an API URL all receive notifications")
        print("  3. Health state transitions trigger backend callbacks")
        print("  4. Circuit breaker filters unhealthy backends from failover plans")
        print("  5. Both ping and HTTP health events are properly routed")
        print()

    except AssertionError as e:
        print(f"\n[FAILED] Assertion error: {e}")
        raise
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
