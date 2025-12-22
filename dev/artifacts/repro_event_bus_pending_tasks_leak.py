"""Repro script for event bus pending tasks memory leak.

This script demonstrates that pending tasks in EventBus might accumulate
if tasks are kept alive by external references.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.event_bus import EventBus


class TestEvent:
    """Test event for event bus."""
    pass


async def test_event_bus_pending_tasks_leak():
    """Test that pending tasks accumulate in EventBus."""
    event_bus = EventBus()
    
    # Keep references to tasks to prevent garbage collection
    task_refs = []
    
    initial_pending_count = len(event_bus._pending_tasks)
    print(f"Initial pending tasks count: {initial_pending_count}")
    
    # Create many events with handlers that take time
    num_events = 1000
    
    async def slow_handler(event):
        await asyncio.sleep(0.01)
    
    # Subscribe handler
    event_bus.subscribe(TestEvent, slow_handler)
    
    # Publish many events without waiting
    for i in range(num_events):
        # Use publish_nowait which adds tasks to _pending_tasks
        event_bus.publish_nowait(TestEvent())
    
    # Give tasks time to start
    await asyncio.sleep(0.05)
    
    # Check pending tasks count
    pending_count = len([t for t in event_bus._pending_tasks if not t.done()])
    total_count = len(event_bus._pending_tasks)
    
    print(f"Pending (not done) tasks: {pending_count}")
    print(f"Total tasks in WeakSet: {total_count}")
    
    # Wait for all tasks to complete
    await asyncio.sleep(0.2)
    
    # Check if completed tasks are cleaned up
    final_pending = len([t for t in event_bus._pending_tasks if not t.done()])
    final_total = len(event_bus._pending_tasks)
    
    print(f"Final pending (not done) tasks: {final_pending}")
    print(f"Final total tasks in WeakSet: {final_total}")
    
    # WeakSet should automatically remove completed tasks when they're GC'd
    # But if tasks are referenced elsewhere, they won't be removed
    if final_total > initial_pending_count + 100:  # Allow some margin
        print("❌ POTENTIAL MEMORY LEAK: Tasks accumulating in WeakSet!")
        print(f"   {final_total - initial_pending_count} tasks still in WeakSet")
        return True
    else:
        print("✓ Tasks cleaned up properly (WeakSet working as expected)")
        return False


async def test_event_bus_with_task_refs():
    """Test that tasks accumulate when kept alive by external references."""
    event_bus = EventBus()
    
    # Keep references to tasks to prevent garbage collection
    task_refs = []
    
    async def slow_handler(event):
        await asyncio.sleep(0.01)
    
    event_bus.subscribe(TestEvent, slow_handler)
    
    # Publish events and keep references
    num_events = 1000
    for i in range(num_events):
        event_bus.publish_nowait(TestEvent())
    
    # Get all tasks from WeakSet (this creates references!)
    # This simulates what might happen if code iterates over _pending_tasks
    await asyncio.sleep(0.05)
    task_refs = list(event_bus._pending_tasks)
    
    print(f"\nKept references to {len(task_refs)} tasks")
    
    # Wait for tasks to complete
    await asyncio.sleep(0.2)
    
    # Check if tasks are still in WeakSet (they should be, because we have references)
    final_total = len(event_bus._pending_tasks)
    print(f"Final total tasks in WeakSet: {final_total}")
    print(f"Tasks with references: {len(task_refs)}")
    
    # This is expected behavior - if tasks are referenced, they stay in WeakSet
    # But this could be a leak if code accidentally keeps references
    if final_total > 100:
        print("⚠️  WARNING: Tasks remain in WeakSet when referenced externally")
        print("   This is expected WeakSet behavior, but could cause leaks")
        print("   if code accidentally keeps references to completed tasks")
        return True
    else:
        print("✓ WeakSet behavior is correct")
        return False


async def main():
    """Run all leak tests."""
    print("=" * 60)
    print("Testing Event Bus Pending Tasks Memory Leaks")
    print("=" * 60)
    
    leak1 = await test_event_bus_pending_tasks_leak()
    leak2 = await test_event_bus_with_task_refs()
    
    print("\n" + "=" * 60)
    if leak1 or leak2:
        print("RESULT: Potential memory leaks detected!")
        sys.exit(1)
    else:
        print("RESULT: No leaks detected")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
