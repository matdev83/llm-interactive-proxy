from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


@pytest.fixture()
def translation_service() -> TranslationService:
    return TranslationService()


def _build_connector(
    config: AppConfig, translation_service: TranslationService
) -> OpenAIConnector:
    client = AsyncMock(spec=httpx.AsyncClient)
    return OpenAIConnector(
        client=client,
        config=config,
        translation_service=translation_service,
    )


def test_health_checks_disabled_by_config(
    monkeypatch: pytest.MonkeyPatch, translation_service: TranslationService
) -> None:
    monkeypatch.delenv("DISABLE_HEALTH_CHECKS", raising=False)
    connector = _build_connector(
        AppConfig(disable_health_checks=True), translation_service
    )
    assert connector._health_check_enabled is False


def test_health_checks_enabled_by_default(
    monkeypatch: pytest.MonkeyPatch, translation_service: TranslationService
) -> None:
    monkeypatch.delenv("DISABLE_HEALTH_CHECKS", raising=False)
    connector = _build_connector(AppConfig(), translation_service)
    assert connector._health_check_enabled is True


def test_env_override_disables_health_checks(
    monkeypatch: pytest.MonkeyPatch, translation_service: TranslationService
) -> None:
    monkeypatch.setenv("DISABLE_HEALTH_CHECKS", "1")
    connector = _build_connector(AppConfig(), translation_service)
    assert connector._health_check_enabled is False
