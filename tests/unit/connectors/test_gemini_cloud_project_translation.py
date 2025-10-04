from __future__ import annotations

from unittest.mock import Mock

import httpx
import pytest
from src.connectors.gemini_cloud_project import GeminiCloudProjectConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


def _make_connector() -> GeminiCloudProjectConnector:
    client = Mock(spec=httpx.AsyncClient)
    config = AppConfig()
    return GeminiCloudProjectConnector(
        client,
        config,
        translation_service=TranslationService(),
        gcp_project_id="test-project",
    )


def test_normalize_openai_response_accepts_dict() -> None:
    connector = _make_connector()
    payload = {"object": "chat.completion"}

    result = connector._normalize_openai_response(payload)

    assert result is payload


def test_normalize_openai_response_uses_model_dump() -> None:
    connector = _make_connector()

    class DummyResponse:
        def model_dump(self, exclude_unset: bool = True) -> dict[str, str]:
            return {"object": "chat.completion"}

    result = connector._normalize_openai_response(DummyResponse())

    assert result == {"object": "chat.completion"}


def test_normalize_openai_response_rejects_unknown_type() -> None:
    connector = _make_connector()

    with pytest.raises(BackendError):
        connector._normalize_openai_response(object())
