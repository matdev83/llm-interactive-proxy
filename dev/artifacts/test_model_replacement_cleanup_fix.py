"""Test script to verify ModelReplacementService cleanup on EoS events.

This script verifies that ModelReplacementEosSubscriber properly calls
cleanup_session() when EoS events are emitted.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.services.model_replacement_eos_subscriber import (
    ModelReplacementEosSubscriber,
)
from src.core.services.model_replacement_service import ModelReplacementService


class MockEventBus:
    """Mock event bus for testing."""

    def __init__(self):
        self._subscribers = {}

    def subscribe(self, event_type, handler):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type, handler):
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(handler)

    async def publish(self, event):
        event_type = type(event)
        if event_type in self._subscribers:
            for handler in self._subscribers[event_type]:
                await handler(event)


class MockBackendRegistry:
    """Mock backend registry for testing."""

    def get_registered_backends(self):
        return ["openai", "gemini"]


async def main():
    """Test that cleanup_session is called on EoS events."""
    print("=" * 80)
    print("ModelReplacementService Cleanup Fix Verification")
    print("=" * 80)
    print()

    # Create config
    config = ReplacementConfig(
        enabled=True,
        probability=0.5,
        backend_model="gemini:gemini-pro",
        turn_count=3,
    )

    # Create service
    registry = MockBackendRegistry()
    service = ModelReplacementService(config, registry)

    # Create mock event bus
    event_bus = MockEventBus()

    # Create subscriber
    subscriber = ModelReplacementEosSubscriber(event_bus, service)

    # Start subscriber
    await subscriber.start()
    print("[OK] Subscriber started")
    print()

    # Create some session state
    print("Creating session state...")
    num_sessions = 100
    for i in range(num_sessions):
        session_id = f"session-{i:04d}"

        # Create a minimal mock RequestContext
        class MockRequestContext:
            def get_header(self, name, default=""):
                return default

        ctx = MockRequestContext()
        service.should_replace(session_id, ctx)

        # Some sessions get disabled
        if i % 10 == 0:
            service.disable_for_session(session_id)

        # Some sessions activate replacement
        if i % 5 == 0:
            await service.activate_replacement(session_id, "openai", "gpt-4")

    print(f"  Created {num_sessions} sessions")
    print(f"  _session_states size: {len(service._session_states)}")
    print(f"  _disabled_sessions size: {len(service._disabled_sessions)}")
    print()

    # Emit EoS events for half the sessions
    print("Emitting EoS events for 50 sessions...")
    cleaned_sessions = []
    for i in range(50):
        session_id = f"session-{i:04d}"
        cleaned_sessions.append(session_id)

        event = RemoteBackendConnectionEndOfSessionEvent(
            session_id=session_id,
            signal_type=EndOfSessionSignalType.FINISH_REASON,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            reason="test",
            protocol="openai",
            request_id=f"req-{i}",
            backend="openai",
        )

        await event_bus.publish(event)

    print(f"  Emitted EoS events for {len(cleaned_sessions)} sessions")
    print()

    # Verify cleanup happened
    print("Verifying cleanup...")
    remaining_states = len(service._session_states)
    remaining_disabled = len(service._disabled_sessions)

    print(f"  Remaining _session_states: {remaining_states}")
    print(f"  Remaining _disabled_sessions: {remaining_disabled}")
    print()

    # Check that cleaned sessions are gone
    cleaned_count = 0
    for session_id in cleaned_sessions:
        if session_id not in service._session_states:
            cleaned_count += 1

    print(f"  Sessions cleaned: {cleaned_count}/{len(cleaned_sessions)}")
    print()

    if cleaned_count == len(cleaned_sessions):
        print("=" * 80)
        print("[OK] FIX VERIFIED: cleanup_session() is called on EoS events")
        print("=" * 80)
    else:
        print("=" * 80)
        print("[FAIL] FIX FAILED: Some sessions were not cleaned up")
        print("=" * 80)

    # Stop subscriber
    await subscriber.stop()
    print("[OK] Subscriber stopped")


if __name__ == "__main__":
    asyncio.run(main())
