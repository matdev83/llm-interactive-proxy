import json
from pathlib import Path

from src.main import build_app
from starlette.testclient import TestClient


def test_save_and_load_persistent_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.json"
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "K")
    monkeypatch.setenv("GEMINI_API_KEY", "G")
    monkeypatch.setenv("LLM_BACKEND", "openrouter")
    app = build_app(config_file=str(cfg_path))
    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        client.app.state.failover_routes["r1"] = {"policy": "k", "elements": ["openrouter:model-a"]}
        client.app.state.session_manager.default_interactive_mode = True
        client.app.state.backend_type = "gemini"
        client.app.state.api_key_redaction_enabled = False
        client.app.state.command_prefix = "$/"
        client.app.state.config_manager.save()

    data = json.loads(cfg_path.read_text())
    assert data["default_backend"] == "gemini"
    assert data["interactive_mode"] is True
    assert data["failover_routes"]["r1"]["elements"] == ["openrouter:model-a"]
    assert data["redact_api_keys_in_prompts"] is False
    assert data["command_prefix"] == "$/"

    app2 = build_app(config_file=str(cfg_path))
    with TestClient(app2, headers={"Authorization": "Bearer test-proxy-key"}) as client2:
        assert client2.app.state.backend_type == "gemini"
        assert client2.app.state.session_manager.default_interactive_mode is True
        assert client2.app.state.failover_routes["r1"]["elements"] == ["openrouter:model-a"]
        assert client2.app.state.api_key_redaction_enabled is False
        assert client2.app.state.command_prefix == "$/"


def test_invalid_persisted_backend(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"default_backend": "gemini"}))
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "K")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BACKEND", "openrouter")
    app = build_app(config_file=str(cfg_path))
    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        assert client.app.state.backend_type == "openrouter"

