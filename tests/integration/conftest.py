import logging
from collections.abc import Generator
from unittest.mock import AsyncMock

import httpx
import pytest
from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector


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
def mock_client() -> AsyncMock:
    """Mock httpx.AsyncClient."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def gemini_oauth_personal_connector(
    mock_client: AsyncMock,
) -> GeminiOAuthPersonalConnector:
    """
    Provides an initialized instance of the GeminiOAuthPersonalConnector
    for integration testing, with dependencies mocked.
    """
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()

    connector = GeminiOAuthPersonalConnector(
        client=mock_client,
        config=config,
        translation_service=translation_service,
    )

    # Assume it's functional for the test, bypassing full initialization
    connector.is_functional = True

    return connector
