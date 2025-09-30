import logging
from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _configure_logging_for_tests() -> Generator[None, None, None]:
    """
    Automatically configure logging for all integration tests to ensure
    consistent output and proper environment tagging.
    """
    from src.core.common.logging_utils import (
        configure_logging_with_environment_tagging,
    )

    # Configure logging to a level that is visible but not too noisy
    # and ensure the environment tag is set to "test".
    configure_logging_with_environment_tagging(level=logging.INFO)
    yield
