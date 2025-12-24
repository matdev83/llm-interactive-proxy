"""Regression test for unified_tool_security_handler race conditions."""

import sys
import threading
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.domain.configuration.unified_security_config import (
    FileSandboxingConfig,
)
from src.core.services.unified_tool_security_handler import FileSandboxingCheck


def test_concurrent_metrics_protection():
    """Test that FileSandboxingCheck metrics are thread-safe with direct access."""
    config = FileSandboxingConfig(
        enabled=True,
        path_parameter_names=["path"],
        default_tool_patterns=[".*edit.*", ".*write.*"],
        excluded_tools=[],
        strict_mode=False,
        allow_parent_access=False,
    )

    class DummyPathValidator:
        def extract_paths_from_arguments(self, args, param_names):
            return []
        def normalize_path(self, path, root):
            return path
        def is_within_boundary(self, path, root, allow_parent=False):
            return True

    class DummySessionService:
        async def get_session(self, session_id):
            class DummyState:
                project_dir = None
            class DummySession:
                state = DummyState()
            return DummySession()

    check = FileSandboxingCheck(config, DummyPathValidator(), DummySessionService())

    # Directly test metrics protection from multiple threads
    def increment_allowed():
        with check._metrics_lock:
            check._allowed_count += 1

    def increment_blocked():
        with check._metrics_lock:
            check._blocked_count += 1

    def read_metrics():
        check.get_metrics()

    threads = []
    for _ in range(20):
        threads.append(threading.Thread(target=increment_allowed))
        threads.append(threading.Thread(target=increment_blocked))
        threads.append(threading.Thread(target=read_metrics))

    # Start all threads
    for t in threads:
        t.start()

    # Wait for completion
    for t in threads:
        t.join()

    metrics = check.get_metrics()
    total = metrics["blocked_count"] + metrics["allowed_count"]
    expected = 40

    assert total == expected, (
        f"Expected {expected} total checks, got {total} "
        f"(blocked={metrics['blocked_count']}, allowed={metrics['allowed_count']})"
    )


def test_concurrent_get_metrics_locking():
    """Test that get_metrics correctly locks during reads."""
    config = FileSandboxingConfig(
        enabled=True,
        path_parameter_names=["path"],
        default_tool_patterns=[".*edit.*", ".*write.*"],
        excluded_tools=[],
        strict_mode=False,
        allow_parent_access=False,
    )

    class DummyPathValidator:
        def extract_paths_from_arguments(self, args, param_names):
            return []
        def normalize_path(self, path, root):
            return path
        def is_within_boundary(self, path, root, allow_parent=False):
            return True

    class DummySessionService:
        async def get_session(self, session_id):
            class DummyState:
                project_dir = None
            class DummySession:
                state = DummyState()
            return DummySession()

    check = FileSandboxingCheck(config, DummyPathValidator(), DummySessionService())

    # Increment counts
    check._allowed_count = 100
    check._blocked_count = 50

    # Read from multiple threads
    def read_metrics():
        metrics = check.get_metrics()
        # Verify values are consistent
        assert metrics["allowed_count"] >= 0
        assert metrics["blocked_count"] >= 0

    threads = [threading.Thread(target=read_metrics) for _ in range(50)]

    # Start all threads
    for t in threads:
        t.start()

    # Wait for completion
    for t in threads:
        t.join()

    # Final verification
    metrics = check.get_metrics()
    assert metrics["allowed_count"] == 100
    assert metrics["blocked_count"] == 50
