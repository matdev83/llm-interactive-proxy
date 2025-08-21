"""Pytest markers for test categorization.

This module defines markers for categorizing tests.
"""

import pytest


def register_markers(config):
    """Register custom markers with pytest.
    
    Args:
        config: The pytest config object
    """
    config.addinivalue_line(
        "markers", "command: tests related to command handling"
    )
    config.addinivalue_line(
        "markers", "session: tests related to session state management"
    )
    config.addinivalue_line(
        "markers", "backend: tests related to backend services"
    )
    config.addinivalue_line(
        "markers", "di: tests that use the dependency injection architecture"
    )
    config.addinivalue_line(
        "markers", "no_global_mock: tests that should not use the global mock"
    )
    config.addinivalue_line(
        "markers", "integration: integration tests that require multiple components"
    )
    config.addinivalue_line(
        "markers", "network: tests that require network access"
    )
    config.addinivalue_line(
        "markers", "loop_detection: tests related to loop detection"
    )
    config.addinivalue_line(
        "markers", "multimodal: tests related to multimodal content"
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
