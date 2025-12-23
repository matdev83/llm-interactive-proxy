"""
Reproduction script for resource leak in cbor_wire_capture_service.py

This script demonstrates the race condition in _maybe_start_flush_task
where multiple concurrent calls can create multiple background flush tasks,
leading to:
1. Multiple tasks running the background flush loop simultaneously
2. Memory leak from accumulating tasks
3. Potential data corruption from concurrent buffer access
"""

import asyncio
import sys
from pathlib import Path
import tempfile
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.config.app_config import AppConfig
from src.core.services.cbor_wire_capture_service import CborWireCaptureService
from src.core.domain.request_context import RequestContext

async def demonstrate_race_condition():
    """
    Demonstrate that concurrent calls to _maybe_start_flush_task
    can create multiple flush tasks, causing a resource leak.
    """
    print("=" * 80)
    print("Resource Leak Demo: cbor_wire_capture_service.py")
    print("=" * 80)
    print()

    # Create temporary capture directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a mock config
        config = MagicMock(spec=AppConfig)
        config.logging = MagicMock()
        config.logging.log_file = None

        # Initialize capture service
        service = CborWireCaptureService(config, temp_dir, "test-session")

        print(f"1. Service initialized with capture_dir={temp_dir}")
        print(f"   _flush_task before any call: {service._flush_task}")
        print()

        # Simulate concurrent calls to _maybe_start_flush_task
        # This can happen when multiple requests come in quickly
        async def simulate_concurrent_start():
            service._maybe_start_flush_task()

        print("2. Calling _maybe_start_flush_task 10 times concurrently...")
        print("   (This simulates multiple requests coming in simultaneously)")
        await asyncio.gather(*[simulate_concurrent_start() for _ in range(10)])
        print()

        # Check how many tasks were created
        # The check `self._flush_task is not None` is NOT atomic
        # so multiple tasks can be created
        print(f"3. _flush_task after concurrent calls: {service._flush_task}")
        print()

        # The issue: While only one task is stored in self._flush_task,
        # multiple tasks may have been created and are still running.
        # Each task runs the _background_flush_loop which sleeps in a loop.

        # Let's verify by looking at all running tasks
        tasks = asyncio.all_tasks()
        flush_tasks = [t for t in tasks if "flush" in str(t).lower()]

        print(f"4. Number of tasks with 'flush' in name: {len(flush_tasks)}")
        print(f"   Expected: 1")
        print(f"   Actual: {len(flush_tasks)}")
        print()

        if len(flush_tasks) > 1:
            print("!!! RESOURCE LEAK DETECTED !!!")
            print("Multiple background flush tasks are running simultaneously.")
            print("Each task holds a reference to the service and continues running.")
            print()
            print("This can lead to:")
            print("  - Memory leak: Each task holds a reference")
            print("  - Data corruption: Multiple tasks flushing the same buffer")
            print("  - CPU waste: Multiple tasks sleeping in loops")

        # Cleanup
        await service.shutdown()
        print()
        print("5. After shutdown, flush task cleared")
        print()

    return len(flush_tasks) > 1

async def simulate_remote_attack():
    """
    Simulate how a remote actor could trigger this resource leak
    by sending many rapid requests that trigger capture methods.
    """
    print("=" * 80)
    print("Remote Attack Simulation")
    print("=" * 80)
    print()
    print("Scenario: Remote attacker sends 1000 rapid requests")
    print("Each request triggers a capture method that calls _maybe_start_flush_task")
    print()

    with tempfile.TemporaryDirectory() as temp_dir:
        config = MagicMock(spec=AppConfig)
        config.logging = MagicMock()
        config.logging.log_file = None

        service = CborWireCaptureService(config, temp_dir, "attack-session")

        # Simulate many rapid concurrent requests
        async def make_request(i):
            context = MagicMock(spec=RequestContext)
            await service.capture_inbound_request(
                context=context,
                session_id=f"session-{i}",
                request_payload={"test": i}
            )

        print("Sending 100 concurrent requests...")
        await asyncio.gather(*[make_request(i) for i in range(100)])

        # Check tasks
        tasks = asyncio.all_tasks()
        flush_tasks = [t for t in tasks if "flush" in str(t).lower()]

        print(f"After 100 concurrent requests:")
        print(f"  Tasks with 'flush' in name: {len(flush_tasks)}")
        print(f"  Expected: 1")
        print(f"  Actual: {len(flush_tasks)}")
        print()

        if len(flush_tasks) > 1:
            print("!!! ATTACK SUCCESSFUL - Resource leak detected !!!")
            print(f"Attacker created {len(flush_tasks)} background tasks")
            print("Each task consumes memory and CPU")
            print()

        await service.shutdown()

    return len(flush_tasks) > 1

async def main():
    print("Resource Leak Reproduction for cbor_wire_capture_service.py")
    print()
    print("Issue: Race condition in _maybe_start_flush_task")
    print("File: src/core/services/cbor_wire_capture_service.py")
    print("Method: _maybe_start_flush_task (lines 240-248)")
    print()
    print("The check-and-set pattern is not atomic:")
    print("  Line 242: if not self._enabled or self._flush_task is not None:")
    print("  Line 246: self._flush_task = loop.create_task(...)")
    print()
    print("Between these lines, another call can pass the check and")
    print("create a second task before the first is assigned.")
    print()

    leak_detected_1 = await demonstrate_race_condition()
    leak_detected_2 = await simulate_remote_attack()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    if leak_detected_1 or leak_detected_2:
        print("Resource leak confirmed!")
        print()
        print("Fix: Use a lock to make the check-and-set atomic, or")
        print("     store the task immediately in a local variable before assignment.")
        sys.exit(1)
    else:
        print("No resource leak detected (may need faster hardware or")
        print("more concurrent operations to trigger the race condition).")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
