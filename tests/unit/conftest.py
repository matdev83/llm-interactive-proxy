import logging
from collections.abc import Generator

import pytest


# Neutralize the heavy global autouse fixture for unit tests only
@pytest.fixture(autouse=True)
def _global_mock_backend_init() -> Generator[None, None, None]:
    """
    This fixture is a placeholder to neutralize a potentially heavier
    autouse fixture from a higher-level conftest.py, ensuring unit tests
    remain lightweight and fast.
    """
    # This fixture does nothing but exists to override others.
    yield


@pytest.fixture(autouse=True)
def _configure_logging_for_tests() -> None:
    """
    Automatically configure logging for all unit tests to ensure
    consistent output and proper environment tagging.
    """
    from src.core.common.logging_utils import (
        configure_logging_with_environment_tagging,
    )

    # Configure logging to a level that is visible but not too noisy
    # and ensure the environment tag is set to "test".
    configure_logging_with_environment_tagging(level=logging.INFO)
