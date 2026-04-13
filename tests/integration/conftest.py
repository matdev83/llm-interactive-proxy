from __future__ import annotations

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


@pytest.fixture
def app_config_integration_default():
    """Minimal AppConfig for integration tests that need default session/backends."""
    from src.core.config.app_config import AppConfig

    return AppConfig.model_validate({})


@pytest.fixture
def app_config_with_openai_backend():
    """
    AppConfig with openai backend enabled for tests that exercise backend routing.

    Uses explicit backend format (e.g. openai:gpt-4) to bypass model-only resolution,
    as required for spec-compliant unknown-model error handling.
    """
    from src.core.config.app_config import AppConfig

    return AppConfig.model_validate(
        {
            "backends": {
                "default_backend": "openai",
                "openai": {"api_key": "test-key-for-routing"},
            },
        }
    )
