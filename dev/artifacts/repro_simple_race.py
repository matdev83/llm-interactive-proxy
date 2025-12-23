"""
Simpler test for the race condition in _maybe_start_flush_task
"""

import asyncio
import sys
from pathlib import Path
import tempfile
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.config.app_config import AppConfig
from src.core.services.cbor_wire_capture_service import CborWireCaptureService

async def simple_race_test():
    """Simple test: start task, then try to start it again."""
    print("=" * 80)
    print("Simple Race Condition Test")
    print("=" * 80)
    print()

    with tempfile.TemporaryDirectory() as temp_dir:
        config = MagicMock(spec=AppConfig)
        config.logging = MagicMock()
        config.logging.log_file = None

        service = CborWireCaptureService(config, temp_dir, "test-session")

        print(f"1. Initial flush_task: {service._flush_task}")

        # Task 1 created during init
        initial_task = service._flush_task
        print(f"2. Initial task created: {initial_task}")

        # Give the initial task a chance to start
        await asyncio.sleep(0.01)

        # Now call _maybe_start_flush_task 10 times
        print("3. Calling _maybe_start_flush_task 10 times...")
        for i in range(10):
            service._maybe_start_flush_task()

        # Check current flush_task
        current_task = service._flush_task
        print(f"4. Current flush_task: {current_task}")
        print(f"   Initial task still same: {initial_task is current_task}")
        print()

        # Count all tasks
        tasks = asyncio.all_tasks()
        flush_tasks = [t for t in tasks if "flush" in str(t).lower()]

        print(f"5. Total flush tasks: {len(flush_tasks)}")
        print(f"   Expected: 1")
        print(f"   Actual: {len(flush_tasks)}")
        print()

        # Print all flush task details
        for i, t in enumerate(flush_tasks):
            print(f"   Task {i+1}: {t}")
            print(f"           Done: {t.done()}")
            print(f"           Cancelled: {t.cancelled()}")
        print()

        if len(flush_tasks) > 1:
            print("!!! RESOURCE LEAK DETECTED !!!")
            print("Multiple background flush tasks are running.")
        else:
            print("No leak detected - only one task running")

        await service.shutdown()

if __name__ == "__main__":
    asyncio.run(simple_race_test())
