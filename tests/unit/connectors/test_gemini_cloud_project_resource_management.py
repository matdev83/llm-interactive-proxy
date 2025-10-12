import asyncio
from typing import Any

import httpx
import pytest

from src.connectors.gemini_cloud_project import GeminiCloudProjectConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


class _DummyResponse:
    def __init__(self, status_code: int = 200, json_data: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._json_data


class _DummySession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def connector() -> GeminiCloudProjectConnector:
    cfg = AppConfig()
    client = httpx.AsyncClient()
    backend = GeminiCloudProjectConnector(
        client,
        cfg,
        translation_service=TranslationService(),
        gcp_project_id="test-project",
    )
    backend.gemini_api_base_url = "https://example.com"
    return backend


@pytest.mark.asyncio
async def test_validate_project_access_closes_session(
    connector: GeminiCloudProjectConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Session(_DummySession):
        def request(self, *args: Any, **kwargs: Any) -> _DummyResponse:
            return _DummyResponse(
                json_data={"cloudaicompanionProject": {"id": connector.gcp_project_id}}
            )

    session = _Session()

    async def _immediate_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(connector, "_get_adc_authorized_session", lambda: session)
    monkeypatch.setattr(asyncio, "to_thread", _immediate_to_thread)

    await connector._validate_project_access()

    assert session.closed is True


@pytest.mark.asyncio
async def test_perform_health_check_closes_session(
    connector: GeminiCloudProjectConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Credentials:
        def __init__(self) -> None:
            self.token = "token"

        def refresh(self, request: Any) -> None:  # pragma: no cover - simple stub
            self.token = "new-token"

    class _Session(_DummySession):
        def __init__(self) -> None:
            super().__init__()
            self.credentials = _Credentials()

    async def _fake_get(url: str, headers: dict[str, str], timeout: float) -> Any:
        return _DummyResponse(status_code=200)

    session = _Session()

    monkeypatch.setattr(connector, "_get_adc_authorized_session", lambda: session)
    monkeypatch.setattr(connector.client, "get", _fake_get)

    result = await connector._perform_health_check()

    assert result is True
    assert session.closed is True
