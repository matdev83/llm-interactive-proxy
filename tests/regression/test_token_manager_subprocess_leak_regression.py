"""Regression test for TokenManager subprocess leak fix.

This test verifies that TokenManager.cleanup() properly terminates subprocesses.
"""

import pytest
import subprocess
import sys

from src.connectors.gemini_base.token_manager import TokenManager


@pytest.mark.asyncio
async def test_cleanup_terminates_subprocess():
    """Test that cleanup() terminates running subprocess."""
    token_manager = TokenManager()
    
    # Launch a subprocess that stays alive
    if sys.platform == "win32":
        cmd = ["python", "-c", "import time; time.sleep(30)"]
    else:
        cmd = ["python3", "-c", "import time; time.sleep(30)"]
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        token_manager._cli_refresh_process = process
        
        # Verify process is running
        assert process.poll() is None
        
        # Call cleanup()
        await token_manager.cleanup()
        
        # Verify process was terminated
        assert process.poll() is not None
        assert token_manager._cli_refresh_process is None
        
    except FileNotFoundError:
        pytest.skip("Python executable not found")


@pytest.mark.asyncio
async def test_cleanup_handles_already_terminated_process():
    """Test that cleanup() handles already terminated process."""
    token_manager = TokenManager()
    
    # Launch a subprocess that completes quickly
    if sys.platform == "win32":
        cmd = ["python", "-c", "pass"]
    else:
        cmd = ["python3", "-c", "pass"]
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        token_manager._cli_refresh_process = process
        
        # Wait for process to complete
        process.wait()
        
        # Call cleanup() - should handle gracefully
        await token_manager.cleanup()
        
        # Verify reference was cleared
        assert token_manager._cli_refresh_process is None
        
    except FileNotFoundError:
        pytest.skip("Python executable not found")


@pytest.mark.asyncio
async def test_cleanup_idempotent():
    """Test that cleanup() can be called multiple times safely."""
    token_manager = TokenManager()
    
    # Call cleanup() multiple times when no process exists
    await token_manager.cleanup()
    await token_manager.cleanup()
    await token_manager.cleanup()
    
    # Should not raise exception
    assert token_manager._cli_refresh_process is None


@pytest.mark.asyncio
async def test_cleanup_handles_none_process():
    """Test that cleanup() handles None process gracefully."""
    token_manager = TokenManager()
    token_manager._cli_refresh_process = None
    
    # Should not raise exception
    await token_manager.cleanup()
    
    assert token_manager._cli_refresh_process is None

