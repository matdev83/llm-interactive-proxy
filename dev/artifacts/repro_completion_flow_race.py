"""Repro script for race condition in backend_completion_flow._cancellation_tasks."""
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def create_and_track_tasks_concurrently():
    """Simulate concurrent additions to _cancellation_tasks set."""
    from src.core.services.backend_completion_flow.service import (
        BackendCompletionFlowOrchestrator,
    )

    # Create orchestrator with mock dependencies
    orchestrator = BackendCompletionFlowOrchestrator(
        availability_checker=None,
        request_preparer=None,
        session_resolver=None,
        backend_invoker=None,
        failover_executor=None,
        wire_capture_orchestrator=None,
        usage_accounting_orchestrator=None,
        exception_normalizer=None,
        stream_formatting_service=None,
    )

    # Create 100 cleanup tasks concurrently
    async def create_and_add_task():
        async def noop():
            await asyncio.sleep(0.01)
            return

        task = asyncio.create_task(noop())
        orchestrator._cancellation_tasks.add(task)
        return task

    tasks = [create_and_add_task() for _ in range(100)]
    created_tasks = await asyncio.gather(*tasks)

    print(f"Expected 100 tasks in _cancellation_tasks")
    print(f"Actual tasks in _cancellation_tasks: {len(orchestrator._cancellation_tasks)}")

    # Check for missing tasks
    missing = len(created_tasks) - len(orchestrator._cancellation_tasks)
    if missing > 0:
        print(f"RACE CONDITION DETECTED: {missing} tasks missing from set!")
        return False
    else:
        print("No race condition detected")
        return True


if __name__ == "__main__":
    for i in range(10):
        print(f"\n--- Run {i+1} ---")
        success = asyncio.run(create_and_track_tasks_concurrently())
        if not success:
            print("Failed on first error - exiting")
            break
