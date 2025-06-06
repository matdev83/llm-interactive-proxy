from fastapi.testclient import TestClient
from src import main as app_main


def test_models_endpoint_lists_all(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False) # Ensure unnumbered key is not present
    monkeypatch.delenv("GEMINI_API_KEY", raising=False) # Ensure unnumbered key is not present
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "K1")
    monkeypatch.setenv("GEMINI_API_KEY_1", "K2") # Changed to numbered key
    monkeypatch.setenv("LLM_BACKEND", "openrouter")
    app = app_main.build_app()
    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        resp = client.get("/models")
        assert resp.status_code == 200
        ids = {m["id"] for m in resp.json()["data"]}
        assert "openrouter:model-a" in ids
        assert "gemini:model-a" in ids
