"""Pytest configuration for property tests.

This module configures logging to INFO level for all property tests to reduce
log spam from DEBUG messages. Property tests often generate many examples via
Hypothesis, and DEBUG logging can create excessive output that stalls the test suite.
"""

import logging

import pytest
from src.core.common.logging_utils import (
    configure_logging_with_environment_tagging,
)


@pytest.fixture(autouse=True)
def _configure_logging_for_property_tests() -> None:
    """
    Automatically configure logging to INFO level for all property tests.

    Property tests use Hypothesis to generate many examples, and each example
    may trigger DEBUG log messages. Setting logging to INFO level prevents
    excessive log output while still allowing tests that specifically test
    logging behavior (via mock loggers) to function correctly.
    """
    configure_logging_with_environment_tagging(level=logging.INFO)

