import logging
from collections.abc import Generator
from unittest.mock import AsyncMock

import httpx
import pytest
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector


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
def gemini_oauth_plan_connector(
    mock_client: AsyncMock,
) -> GeminiOAuthPlanConnector:
    """
    Provides an initialized instance of the GeminiOAuthPlanConnector
    for integration testing, with dependencies mocked.
    """
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()

    connector = GeminiOAuthPlanConnector(
        client=mock_client,
        config=config,
        translation_service=translation_service,
    )

    # Assume it's functional for the test, bypassing full initialization
    connector.is_functional = True

    return connector


@pytest.fixture(autouse=True)
async def mock_qwen_oauth_refresh(monkeypatch):
    """Auto-mock qwen-oauth token refresh to avoid API calls in integration tests."""
    from src.connectors.qwen_oauth import QwenOAuthConnector

    original_refresh = QwenOAuthConnector._refresh_token_if_needed
    original_validate = QwenOAuthConnector._validate_runtime_credentials

    async def mock_refresh(self):
        # If credentials are set and not expired, return True
        if hasattr(self, "_oauth_credentials") and self._oauth_credentials:
            import asyncio

            expiry = self._oauth_credentials.get("expiry_date", 0)
            current_time = int(asyncio.get_event_loop().time() * 1000)
            if expiry > current_time:
                return True
        # Otherwise call original
        return await original_refresh(self)

    async def mock_validate(self):
        # If credentials are set and not expired, validate as true
        if hasattr(self, "_oauth_credentials") and self._oauth_credentials:
            import asyncio

            expiry = self._oauth_credentials.get("expiry_date", 0)
            current_time = int(asyncio.get_event_loop().time() * 1000)
            if expiry > current_time:
                return True
        # Otherwise call original
        return await original_validate(self)

    monkeypatch.setattr(QwenOAuthConnector, "_refresh_token_if_needed", mock_refresh)
    monkeypatch.setattr(
        QwenOAuthConnector, "_validate_runtime_credentials", mock_validate
    )
