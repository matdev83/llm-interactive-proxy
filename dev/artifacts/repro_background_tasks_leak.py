"""Repro script for background tasks memory leak.

This script demonstrates that completed background tasks accumulate
in AppLifecycle and ResponseProcessor when no new tasks are added.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI
from src.core.app.lifecycle import AppLifecycle


async def test_app_lifecycle_background_tasks_leak():
    """Test that completed background tasks accumulate in AppLifecycle."""
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})

    initial_count = len(lifecycle._background_tasks)
    print(f"Initial background tasks count: {initial_count}")

    # Create and complete many tasks
    num_tasks = 1000
    for i in range(num_tasks):

        async def dummy_task(task_id=i):
            await asyncio.sleep(0.001)
            return task_id

        task = asyncio.create_task(dummy_task())
        lifecycle._background_tasks.append(task)
        task.add_done_callback(lifecycle._remove_completed_task)

    # Wait for all tasks to complete
    await asyncio.sleep(0.1)

    # Check if tasks are cleaned up
    final_count = len(lifecycle._background_tasks)
    print(f"Final background tasks count: {final_count}")
    print(f"Expected: ~{initial_count}, Actual: {final_count}")

    if final_count > initial_count + 10:  # Allow some margin
        print("❌ MEMORY LEAK CONFIRMED: Completed tasks are accumulating!")
        print(f"   {final_count - initial_count} completed tasks not cleaned up")
        return True
    else:
        print("✓ No leak detected (tasks cleaned up properly)")
        return False


async def test_response_processor_background_tasks_leak():
    """Test that completed background tasks accumulate in ResponseProcessor."""
    # Create a minimal ResponseProcessor via DI with mock parser
    from src.core.config.app_config import AppConfig
    from src.core.di.container import ServiceCollection
    from src.core.di.registration_helpers.core_foundational import (
        register_application_state_services,
    )
    from src.core.di.registrations import streaming, tooling
    from src.core.di.registrations.core import register
    from src.core.interfaces.response_parser_interface import IResponseParser
    from src.core.interfaces.response_processor_interface import IResponseProcessor

    class MockParser(IResponseParser):
        def parse_response(self, response):
            return {}

        def extract_content(self, parsed):
            return ""

        def extract_usage(self, parsed):
            return {}

        def extract_metadata(self, parsed):
            return {}

    # Create DI container with mock parser
    services = ServiceCollection()
    config = AppConfig()
    services.add_instance(AppConfig, config)

    # Register mock parser
    parser = MockParser()
    services.add_instance(IResponseParser, parser)  # type: ignore[type-abstract]

    # Register core services
    register_application_state_services(services)
    streaming.register(services, config)
    tooling.register(services, config)
    register(services, config)

    # Get ResponseProcessor from DI
    provider = services.build_service_provider()
    processor = provider.get_required_service(IResponseProcessor)  # type: ignore[type-abstract]

    initial_count = len(processor._background_tasks)
    print(f"\nInitial background tasks count: {initial_count}")

    # Create and complete many tasks
    num_tasks = 1000
    for i in range(num_tasks):

        async def dummy_task(task_id=i):
            await asyncio.sleep(0.001)
            return task_id

        task = asyncio.create_task(dummy_task())
        processor.add_background_task(task)

    # Wait for all tasks to complete
    await asyncio.sleep(0.1)

    # Check if tasks are cleaned up
    final_count = len(processor._background_tasks)
    print(f"Final background tasks count: {final_count}")
    print(f"Expected: ~{initial_count}, Actual: {final_count}")

    if final_count > initial_count + 10:  # Allow some margin
        print("❌ MEMORY LEAK CONFIRMED: Completed tasks are accumulating!")
        print(f"   {final_count - initial_count} completed tasks not cleaned up")
        return True
    else:
        print("✓ No leak detected (tasks cleaned up properly)")
        return False


async def main():
    """Run all leak tests."""
    print("=" * 60)
    print("Testing Background Tasks Memory Leaks")
    print("=" * 60)

    leak1 = await test_app_lifecycle_background_tasks_leak()
    leak2 = await test_response_processor_background_tasks_leak()

    print("\n" + "=" * 60)
    if leak1 or leak2:
        print("RESULT: Memory leaks confirmed!")
        sys.exit(1)
    else:
        print("RESULT: No leaks detected")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
