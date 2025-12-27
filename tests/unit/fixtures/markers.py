"""Pytest markers for test categorization.

This module defines markers for categorizing tests.
"""

import pytest


def register_markers(config):
    """Register custom markers with pytest.

    Args:
        config: The pytest config object
    """
    config.addinivalue_line("markers", "command: tests related to command handling")
    config.addinivalue_line(
        "markers", "session: tests related to session state management"
    )
    config.addinivalue_line("markers", "backend: tests related to backend services")
    config.addinivalue_line(
        "markers", "di: tests that use the dependency injection architecture"
    )
    config.addinivalue_line(
        "markers", "no_global_mock: tests that should not use the global mock"
    )
    config.addinivalue_line(
        "markers", "integration: integration tests that require multiple components"
    )
    config.addinivalue_line("markers", "network: tests that require network access")
    config.addinivalue_line(
        "markers", "loop_detection: tests related to loop detection"
    )
    config.addinivalue_line(
        "markers", "multimodal: tests related to multimodal content"
    )
    config.addinivalue_line(
        "markers",
        "real_time: marks tests that legitimately require real system wall-clock time (requires reason parameter)",
    )


# Define the markers for use in tests
command = pytest.mark.command
session = pytest.mark.session
backend = pytest.mark.backend
di = pytest.mark.di
no_global_mock = pytest.mark.no_global_mock
integration = pytest.mark.integration
network = pytest.mark.network
loop_detection = pytest.mark.loop_detection
multimodal = pytest.mark.multimodal


def real_time(reason: str) -> pytest.MarkDecorator:
    """Mark a test as requiring real system wall-clock time.

    This marker identifies tests that legitimately require real system time
    and cannot use test-controlled time. The reason parameter is mandatory
    to ensure exceptions are intentional and reviewable.

    Args:
        reason: Non-empty explanation of why this test requires real time.
            This should be reviewable in code review.

    Returns:
        pytest.MarkDecorator that can be applied to test functions.

    Raises:
        ValueError: If reason is empty or whitespace-only.

    Example:
        @real_time(reason="This test measures actual network latency")
        def test_network_performance():
            ...
    """
    if not reason or not reason.strip():
        raise ValueError("real_time marker requires a non-empty reason parameter")

    return pytest.mark.real_time(reason=reason)
