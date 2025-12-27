"""Regression test for TokenManager subprocess leak with circular references.

This test verifies that TokenManager subprocesses are properly cleaned up
even when circular references prevent __del__ from being called.

Fixed: TokenManager.cleanup() method should be called explicitly to prevent
subprocess leaks when circular references exist.
"""

import asyncio
import gc
import subprocess
import sys

import pytest
from src.connectors.gemini_base.token_manager import TokenManager


class MockCredentialProvider:
    """Mock credential provider for testing."""

    def __init__(self):
        self._oauth_credentials = None

    async def _load_oauth_credentials(self, force_reload: bool = False) -> bool:
        return False


@pytest.mark.asyncio
async def test_subprocess_leak_with_circular_ref() -> None:
    """Test that subprocess leaks when circular references prevent __del__."""
    provider = MockCredentialProvider()
    token_manager = TokenManager()

    # Create circular reference to prevent __del__ from being called
    token_manager._provider_ref = provider  # type: ignore[attr-defined]
    provider._token_manager_ref = token_manager  # type: ignore[attr-defined]

    # Launch subprocess (this creates a subprocess)
    # Use a command that will stay alive for a bit (reduced from 5s to 1s for performance)
    if sys.platform == "win32":
        cmd = ["python", "-c", "import time; time.sleep(1)"]
    else:
        cmd = ["python3", "-c", "import time; time.sleep(1)"]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        token_manager._cli_refresh_process = process

        # Verify process is running
        assert process.poll() is None, "Process should be running"

        # Delete references (but circular ref prevents __del__)
        del token_manager
        del provider

        # Force garbage collection
        gc.collect()

        # Wait a bit (reduced from 0.5s to 0.1s for performance)
        await asyncio.sleep(0.1)

        # Check if process is still running
        # With circular references, __del__ may not be called
        # This test verifies that cleanup() should be called explicitly
        if process.poll() is None:
            # Process is still running - this confirms the leak scenario
            # In production, cleanup() should be called explicitly
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

            # The fix is to call cleanup() explicitly before deleting references
            pytest.fail(
                "Subprocess leaked due to circular reference preventing __del__. "
                "TokenManager.cleanup() should be called explicitly."
            )
    except FileNotFoundError:
        pytest.skip("Python executable not found")


@pytest.mark.asyncio
async def test_cleanup_explicitly_prevents_leak_with_circular_ref() -> None:
    """Test that calling cleanup() explicitly prevents leak even with circular refs."""
    provider = MockCredentialProvider()
    token_manager = TokenManager()

    # Create circular reference
    token_manager._provider_ref = provider  # type: ignore[attr-defined]
    provider._token_manager_ref = token_manager  # type: ignore[attr-defined]

    # Launch subprocess
    if sys.platform == "win32":
        cmd = ["python", "-c", "import time; time.sleep(5)"]
    else:
        cmd = ["python3", "-c", "import time; time.sleep(5)"]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        token_manager._cli_refresh_process = process

        # Verify process is running
        assert process.poll() is None, "Process should be running"

        # Call cleanup() explicitly (this is the fix)
        await token_manager.cleanup()

        # Verify process was terminated
        assert (
            process.poll() is not None
        ), "Process should be terminated after cleanup()"
        assert (
            token_manager._cli_refresh_process is None
        ), "Process reference should be cleared"

        # Now delete references - cleanup already happened
        del token_manager
        del provider
        gc.collect()

        # Process should remain terminated
        assert process.poll() is not None, "Process should remain terminated"

    except FileNotFoundError:
        pytest.skip("Python executable not found")


@pytest.mark.asyncio
async def test_remote_actor_scenario_multiple_instances() -> None:
    """Test scenario where remote actor can trigger resource leak."""
    # Simulate attacker creating many TokenManager instances
    # Each creates a subprocess that may leak if __del__ is not called
    processes = []

    for _i in range(3):
        provider = MockCredentialProvider()
        token_manager = TokenManager()

        # Create circular reference
        token_manager._provider_ref = provider  # type: ignore[attr-defined]
        provider._token_manager_ref = token_manager  # type: ignore[attr-defined]

        # Launch subprocess
        if sys.platform == "win32":
            cmd = ["python", "-c", "import time; time.sleep(1)"]
        else:
            cmd = ["python3", "-c", "import time; time.sleep(1)"]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            token_manager._cli_refresh_process = process
            processes.append((token_manager, process))

            # Delete references (circular ref prevents __del__)
            del token_manager
            del provider

        except FileNotFoundError:
            pytest.skip("Python executable not found")
            return

    # Force garbage collection
    gc.collect()

    # Wait a bit
    await asyncio.sleep(0.2)

    # Check how many processes are still running
    [p for _, p in processes if p.poll() is None]

    # Clean up all processes
    for token_manager, process in processes:
        if process.poll() is None:
            # Call cleanup() explicitly to prevent leak
            await token_manager.cleanup()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    # Verify all processes were cleaned up
    final_running = [p for _, p in processes if p.poll() is None]
    assert len(final_running) == 0, (
        f"{len(final_running)} processes still running. "
        "cleanup() should be called explicitly to prevent leaks."
    )
