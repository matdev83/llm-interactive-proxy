from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app


def test_models_endpoint_lists_all(monkeypatch) -> None:
    # No backend mocking required: controller uses a default model list if none discovered
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()
    with TestClient(app) as client:
        resp = client.get("/models")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) > 0


def test_v1_models_endpoint_lists_all(monkeypatch) -> None:
    # No backend mocking required: controller uses a default model list if none discovered
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()
    with TestClient(app) as client:
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) > 0


import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
