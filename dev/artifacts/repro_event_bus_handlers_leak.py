"""Repro script to test EventBus handler accumulation memory leak.

This script tests if EventBus handlers accumulate without bounds when
handlers are subscribed but never unsubscribed.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.event_bus import EventBus


class TestEvent:
    """Test event class."""

    pass


async def test_handler(event: TestEvent) -> None:
    """Test event handler."""
    pass


async def main() -> None:
    """Test EventBus handler accumulation."""
    # Use a lower limit for testing
    max_handlers = 1000
    bus = EventBus(max_total_handlers=max_handlers)

    print("Testing EventBus handler accumulation...")
    print("=" * 60)
    print(f"Max handlers limit: {max_handlers}")

    # Subscribe many handlers without unsubscribing
    num_handlers = 1500  # More than max to test limit
    print(f"Attempting to subscribe {num_handlers} handlers...")

    for i in range(num_handlers):
        # Create a new handler function each time
        async def handler(event: TestEvent) -> None:
            pass

        bus.subscribe(TestEvent, handler)

        if (i + 1) % 500 == 0:
            # Count total handlers
            total_handlers = sum(
                len(handlers)
                for topic_map in bus._handlers.values()
                for handlers in topic_map.values()
            )
            print(f"  Attempted {i + 1} handlers, total handlers in bus: {total_handlers}")

    # Count final handlers
    total_handlers = sum(
        len(handlers)
        for topic_map in bus._handlers.values()
        for handlers in topic_map.values()
    )

    print(f"\nFinal handler count: {total_handlers}")
    print(f"Attempted: {num_handlers}")
    print(f"Max limit: {max_handlers}")

    if total_handlers <= max_handlers:
        print("\n[FIXED] EventBus handler limit is working")
        print(f"  Handler count ({total_handlers}) is within limit ({max_handlers})")
    elif total_handlers == num_handlers:
        print("\n[CONFIRMED] EventBus handlers accumulate without bounds")
        print("  Issue: Handler limit is not being enforced")
    else:
        print(f"\n[PARTIAL] Some handlers were blocked (got {total_handlers}, attempted {num_handlers})")


if __name__ == "__main__":
    asyncio.run(main())
