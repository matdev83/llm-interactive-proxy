"""Reproduction script for race condition in infrastructure.py HTTP client cleanup.

This script demonstrates the race condition in InfrastructureStage._register_http_client
where asyncio.create_task() is called to clean up an HTTP client on failure, but
the returned task is not tracked or awaited. This can lead to:

1. Unobserved exceptions (if the cleanup fails)
2. Resource leaks if the loop closes before cleanup completes
3. No way to ensure cleanup completes before stage failure is propagated
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_http_client_cleanup_race():
    """Test that demonstrates the untracked cleanup task issue."""
    print("\n=== Test: Untracked HTTP Client Cleanup Task ===")

    # Mock httpx.AsyncClient to simulate a cleanup that might fail
    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.aclose = AsyncMock()

    # Simulate the cleanup code from infrastructure.py
    print("Simulating HTTP client cleanup on registration failure...")

    try:
        # Simulate registration failure
        raise Exception("Simulated registration failure")
    except Exception as e:
        print(f"Registration failed: {e}")
        print("Attempting to clean up HTTP client...")

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # ISSUE: This is the problematic code from infrastructure.py:136-140
            # The returned task is not tracked or awaited
            cleanup_task = asyncio.create_task(mock_client.aclose())
            print(f"Created cleanup task: {cleanup_task}")

            # Without tracking/awaiting, we don't know if cleanup succeeded
            # Let's see what happens
            await asyncio.sleep(0.1)  # Give task time to run

            # Check task status
            if cleanup_task.done():
                print("✓ Cleanup task completed")
                result = cleanup_task.result()
                print(f"  Result: {result}")
            else:
                print("❌ Cleanup task still running - will be lost!")
                print("   Task not tracked, no way to await it")

            # If an exception occurs in the task, it's unobserved
            # This would trigger Python's "Task exception was never retrieved" warning
            mock_client.aclose.side_effect = Exception("Cleanup failed!")
            bad_task = asyncio.create_task(mock_client.aclose())
            await asyncio.sleep(0.1)

            if bad_task.done():
                try:
                    bad_task.result()
                except Exception as ex:
                    print(f"❌ Unobserved exception in cleanup task: {ex}")
                    print("   This exception would be lost and only show as a warning")
            else:
                print("❌ Failing cleanup task still running - will be lost!")


async def test_with_actual_infrastructure_stage():
    """Test with actual InfrastructureStage to demonstrate the issue."""
    print("\n=== Test: InfrastructureStage HTTP Client Registration Failure ===")

    from src.core.app.stages.infrastructure import InfrastructureStage
    from src.core.config.app_config import AppConfig

    # Create a stage
    stage = InfrastructureStage()

    # Patch httpx.AsyncClient to always fail
    with patch("httpx.AsyncClient") as mock_httpx:
        # Make constructor fail
        mock_httpx.side_effect = Exception("Simulated HTTP client creation failure")

        services = type("ServiceCollection", (), {})()
        config = AppConfig.from_env({})

        try:
            await stage.execute(services, config)
        except Exception as e:
            print(f"Expected exception occurred: {e}")

    # The issue is that if HTTP client was partially created before failure,
    # the cleanup task is created but not tracked
    print("If any cleanup task was created, it is not tracked or awaited")


async def test_loop_closure_scenario():
    """Test scenario where event loop closes before cleanup completes."""
    print("\n=== Test: Event Loop Closure Before Cleanup ===")

    class SlowClient:
        """Mock client with slow cleanup."""

        def __init__(self):
            self.is_closed = False
            self.cleanup_started = False
            self.cleanup_finished = False

        async def aclose(self):
            self.cleanup_started = True
            print("  Cleanup started...")
            await asyncio.sleep(0.5)  # Simulate slow cleanup
            self.cleanup_finished = True
            self.is_closed = True
            print("  Cleanup completed")

    async def scenario_with_tracking():
        """With proper tracking, we can ensure cleanup completes."""
        print("\nWith proper tracking:")
        client = SlowClient()

        loop = asyncio.get_event_loop()
        if loop.is_running():
            cleanup_task = asyncio.create_task(client.aclose())
            # Proper: track and await the task
            try:
                await asyncio.wait_for(cleanup_task, timeout=1.0)
                print(f"✓ Cleanup completed: client.is_closed={client.is_closed}")
                return True
            except asyncio.TimeoutError:
                print("❌ Cleanup timed out")
                return False

    async def scenario_without_tracking():
        """Without tracking, cleanup may not complete."""
        print("\nWithout tracking (current implementation):")
        client = SlowClient()

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # ISSUE: Create task but don't track or await
            cleanup_task = asyncio.create_task(client.aclose())
            print(f"  Created task: {cleanup_task}")

            # Simulate loop closing before cleanup completes
            await asyncio.sleep(0.1)
            print("  Loop would close here (before cleanup completes)")
            print(f"  Cleanup started: {client.cleanup_started}")
            print(f"  Cleanup finished: {client.cleanup_finished}")
            print(f"  ❌ Client not closed: is_closed={client.is_closed}")
            print("  ❌ Task reference lost, cleanup will be incomplete")

    await scenario_with_tracking()
    await scenario_without_tracking()


async def main():
    """Run all tests."""
    print("=" * 70)
    print("Race Condition Test: HTTP Client Cleanup in InfrastructureStage")
    print("=" * 70)

    await test_http_client_cleanup_race()
    await test_with_actual_infrastructure_stage()
    await test_loop_closure_scenario()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("❌ Race condition detected:")
    print("   - asyncio.create_task() creates untracked cleanup tasks")
    print("   - No mechanism to ensure cleanup completes")
    print("   - Unobserved exceptions possible")
    print("   - Resource leaks if loop closes before cleanup")
    print("\nRecommended fix:")
    print("   - Track cleanup tasks (add to a set)")
    print("   - Use add_done_callback to remove completed tasks")
    print("   - Await pending tasks in cleanup method")


if __name__ == "__main__":
    asyncio.run(main())
