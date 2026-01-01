from __future__ import annotations

import logging
from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx
import pytest

if TYPE_CHECKING:
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
    from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
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

            expiry = self._oauth_credentials.get("expiry_date", 0)
            from src.core.services.time_source_service import TimeSource

            current_time = int(TimeSource().unix_time_s() * 1000)
            if expiry > current_time:
                return True
        # Otherwise call original
        return await original_refresh(self)

    async def mock_validate(self):
        # If credentials are set and not expired, validate as true
        if hasattr(self, "_oauth_credentials") and self._oauth_credentials:

            expiry = self._oauth_credentials.get("expiry_date", 0)
            from src.core.services.time_source_service import TimeSource

            current_time = int(TimeSource().unix_time_s() * 1000)
            if expiry > current_time:
                return True
        # Otherwise call original
        return await original_validate(self)

    monkeypatch.setattr(QwenOAuthConnector, "_refresh_token_if_needed", mock_refresh)
    monkeypatch.setattr(
        QwenOAuthConnector, "_validate_runtime_credentials", mock_validate
    )


@pytest.fixture
def app_config_legacy_log_disabled():
    """
    Provides an AppConfig instance with emit_legacy_steering_log set to False.

    Note: Legacy steering handlers have been removed. Unified steering is now
    the only implementation, so no need to explicitly configure handler toggles.
    """
    from src.core.config.app_config import AppConfig

    return AppConfig.model_validate(
        {
            "session": {
                "tool_call_reactor": {
                    "emit_legacy_steering_log": False,
                },
            }
        }
    )


@pytest.fixture
def app_config_legacy_log_enabled():
    """
    Provides an AppConfig instance with emit_legacy_steering_log set to True.

    This enables both the structured log and the legacy-formatted log for
    backward compatibility with existing monitoring dashboards.
    """
    from src.core.config.app_config import AppConfig

    return AppConfig.model_validate(
        {
            "session": {
                "tool_call_reactor": {
                    "emit_legacy_steering_log": True,
                },
            }
        }
    )
