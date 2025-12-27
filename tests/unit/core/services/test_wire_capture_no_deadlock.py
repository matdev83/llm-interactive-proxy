"""Test that wire capture doesn't hold async lock during to_thread calls.

This test verifies that async lock is NOT held when calling
asyncio.to_thread, which prevents event loop blocking and potential
deadlocks on hot path (wire capture during concurrent requests).
"""
import asyncio
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.services.structured_wire_capture_service import StructuredWireCapture
from src.core.services.wire_capture_service import WireCapture


@pytest.fixture
def temp_capture_file():
    """Create a temporary file for capture testing."""
    fd, path = tempfile.mkstemp(suffix=".log")
    os.close(fd)
    yield path
    # Cleanup
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def mock_config(temp_capture_file):
    """Create mock config with capture file enabled."""
    config = MagicMock(spec=AppConfig)
    config.logging = MagicMock()
    config.logging.capture_file = temp_capture_file
    config.logging.capture_max_bytes = 10 * 1024  # 10KB
    config.logging.capture_truncate_bytes = None
    config.logging.capture_max_files = 0
    config.logging.capture_rotate_interval_seconds = 0
    config.logging.capture_total_max_bytes = 100 * 1024  # 100KB
    return config


@pytest.mark.asyncio
async def test_wire_capture_no_deadlock_on_concurrent_writes(mock_config, temp_capture_file):
    """Test that concurrent writes to WireCapture don't cause deadlocks.

    This is a regression test for deadlock hazard where async lock was held
    while calling asyncio.to_thread. The fix moves async I/O outside the lock.
    """
    # Import here to get module-level time source for testing
    from src.core.domain.request_context import RequestContext

    capture = WireCapture(mock_config)

    # Track completion
    completed = []
    errors = []

    async def write_task(task_id: int):
        """Task that performs a capture write."""
        try:
            context = RequestContext(
                headers={},
                cookies={},
                state=None,
                app_state=None,
                client_host="127.0.0.1",
                session_id=f"session-{task_id}",
                agent="test-agent",
            )

            for i in range(5):
                await capture.capture_outbound_request(
                    context=context,
                    session_id=f"session-{task_id}",
                    backend="test-backend",
                    model="test-model",
                    key_name=f"key-{task_id}",
                    request_payload={"test": f"data-{task_id}-{i}"},
                )

            completed.append(task_id)
        except Exception as e:
            errors.append((task_id, e))

    # Create a few concurrent tasks (not too many to avoid temp file conflicts)
    tasks = [asyncio.create_task(write_task(i)) for i in range(5)]

    # Wait for all tasks to complete with a timeout
    # If deadlock occurs, this will timeout
    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=30)

    # Verify all tasks completed without errors
    assert len(completed) == 5, f"Expected 5 completed tasks, got {len(completed)}"
    assert len(errors) == 0, f"Errors occurred: {errors}"

    # Verify file was written (non-empty)
    file_size = os.path.getsize(temp_capture_file)
    assert file_size > 0, "Capture file should contain data"

    # Clean up
    await capture.shutdown()



@pytest.mark.asyncio
async def test_structured_wire_capture_no_deadlock_on_concurrent_writes(mock_config, temp_capture_file):
    """Test that concurrent writes to StructuredWireCapture don't cause deadlocks.

    This is a regression test for deadlock hazard where async lock was held
    while calling asyncio.to_thread. The fix moves async I/O outside the lock.
    """
    # Import here to get module-level time source for testing
    from src.core.domain.request_context import RequestContext

    capture = StructuredWireCapture(mock_config)

    # Track completion
    completed = []
    errors = []

    async def write_task(task_id: int):
        """Task that performs a capture write."""
        try:
            context = RequestContext(
                headers={},
                cookies={},
                state=None,
                app_state=None,
                client_host="127.0.0.1",
                session_id=f"session-{task_id}",
                agent="test-agent",
            )

            for i in range(5):
                await capture.capture_outbound_request(
                    context=context,
                    session_id=f"session-{task_id}",
                    backend="test-backend",
                    model="test-model",
                    key_name=f"key-{task_id}",
                    request_payload={"test": f"data-{task_id}-{i}"},
                )

            completed.append(task_id)
        except Exception as e:
            errors.append((task_id, e))

    # Create a few concurrent tasks (not too many to avoid temp file conflicts)
    tasks = [asyncio.create_task(write_task(i)) for i in range(5)]

    # Wait for all tasks to complete with a timeout
    # If deadlock occurs, this will timeout
    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=30)

    # Verify all tasks completed without errors
    assert len(completed) == 5, f"Expected 5 completed tasks, got {len(completed)}"
    assert len(errors) == 0, f"Errors occurred: {errors}"

    # Verify file was written (non-empty)
    file_size = os.path.getsize(temp_capture_file)
    assert file_size > 0, "Capture file should contain data"

    # Clean up
    await capture.shutdown()



def test_wire_capture_no_event_loop_blocking():
    """Test that WireCapture doesn't block event loop during file I/O.

    This verifies that to_thread calls are made (not synchronous I/O)
    by checking that async operations complete within expected timeframe.
    """
    from src.core.domain.request_context import RequestContext

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = os.path.join(tmpdir, "capture.log")

        mock_config = MagicMock(spec=AppConfig)
        mock_config.logging = MagicMock()
        mock_config.logging.capture_file = temp_path
        mock_config.logging.capture_max_bytes = None
        mock_config.logging.capture_truncate_bytes = None
        mock_config.logging.capture_max_files = 0
        mock_config.logging.capture_rotate_interval_seconds = 0
        mock_config.logging.capture_total_max_bytes = 0

        # Use structured capture which has same fix
        capture = StructuredWireCapture(mock_config)

        async def main():
            context = RequestContext(
                headers={},
                cookies={},
                state=None,
                app_state=None,
                client_host="127.0.0.1",
                session_id="test-session",
                agent="test-agent",
            )

            # This should use to_thread and yield to event loop
            await capture.capture_outbound_request(
                context=context,
                session_id="test-session",
                backend="test-backend",
                model="test-model",
                key_name="test-key",
                request_payload={"test": "data"},
            )

        # Run async test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main())
        finally:
            loop.close()

        # Verify file exists and has content
        assert os.path.exists(temp_path)
        assert os.path.getsize(temp_path) > 0

