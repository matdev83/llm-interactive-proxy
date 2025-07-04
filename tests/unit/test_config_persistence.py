import json
from pathlib import Path

from src.main import build_app
from starlette.testclient import TestClient

def _setup_initial_env_for_config_test(monkeypatch):
    """Sets up initial environment variables for config persistence tests."""
    for i in range(1, 21): # Max 20 numbered keys
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "K_initial") # Use distinct value for clarity
    monkeypatch.setenv("GEMINI_API_KEY", "G_initial")
    monkeypatch.setenv("LLM_BACKEND", "openrouter") # Initial default

def _apply_test_state_modifications(app_client: TestClient, modifications: dict):
    """Applies a dictionary of state modifications to the app."""
    if "failover_routes" in modifications:
        app_client.app.state.failover_routes.update(modifications["failover_routes"])
    if "default_interactive_mode" in modifications:
        app_client.app.state.session_manager.default_interactive_mode = modifications["default_interactive_mode"]
    if "backend_type" in modifications:
        app_client.app.state.backend_type = modifications["backend_type"]
    if "api_key_redaction_enabled" in modifications:
        app_client.app.state.api_key_redaction_enabled = modifications["api_key_redaction_enabled"]
    if "command_prefix" in modifications:
        app_client.app.state.command_prefix = modifications["command_prefix"]
    # Add more state modifications here as needed

def _assert_json_config_matches(config_path: Path, expected_data: dict):
    """Asserts that the content of the JSON config file matches expected data."""
    saved_data = json.loads(config_path.read_text())
    assert saved_data["default_backend"] == expected_data["backend_type"]
    assert saved_data["interactive_mode"] == expected_data["default_interactive_mode"]
    assert saved_data["failover_routes"] == expected_data["failover_routes"]
    assert saved_data["redact_api_keys_in_prompts"] == expected_data["api_key_redaction_enabled"]
    assert saved_data["command_prefix"] == expected_data["command_prefix"]

def _assert_app_state_matches_expected(app_client: TestClient, expected_data: dict):
    """Asserts that the app's current state matches the expected data."""
    assert app_client.app.state.backend_type == expected_data["backend_type"]
    assert app_client.app.state.session_manager.default_interactive_mode == expected_data["default_interactive_mode"]
    assert app_client.app.state.failover_routes == expected_data["failover_routes"]
    assert app_client.app.state.api_key_redaction_enabled == expected_data["api_key_redaction_enabled"]
    assert app_client.app.state.command_prefix == expected_data["command_prefix"]


def test_save_and_load_persistent_config(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "cfg.json"
    _setup_initial_env_for_config_test(monkeypatch)

    expected_state_values = {
        "failover_routes": {"r1": {"policy": "k", "elements": ["openrouter:model-a"]}},
        "default_interactive_mode": True,
        "backend_type": "gemini",
        "api_key_redaction_enabled": False,
        "command_prefix": "$/"
    }

    # --- First app instance: modify state and save ---
    app1 = build_app(config_file=str(cfg_path))
    with TestClient(app1, headers={"Authorization": "Bearer test-proxy-key"}) as client1:
        # Ensure functional_backends is populated for route validation during save/load
        client1.app.state.functional_backends = {"openrouter", "gemini"}
        if hasattr(client1.app.state, "openrouter_backend"): # Ensure backend objects exist
             client1.app.state.openrouter_backend.available_models = ["model-a", "model-b"]

        _apply_test_state_modifications(client1, expected_state_values)
        client1.app.state.config_manager.save()

    # --- Assertions on the saved JSON file ---
    _assert_json_config_matches(cfg_path, expected_state_values)

    # --- Second app instance: load config and assert state ---
    # Note: _setup_initial_env_for_config_test is NOT called again here
    # to ensure that the loaded config overrides any initial env/defaults.
    # However, for model availability, we might need to ensure backends are functional.
    monkeypatch.setenv("OPENROUTER_API_KEY", "K_loaded") # Simulate different env for loading
    monkeypatch.setenv("GEMINI_API_KEY", "G_loaded")

    app2 = build_app(config_file=str(cfg_path))
    with TestClient(app2, headers={"Authorization": "Bearer test-proxy-key"}) as client2:
        # For loaded config to correctly apply routes, models need to be "available"
        client2.app.state.functional_backends = {"openrouter", "gemini"}
        if hasattr(client2.app.state, "openrouter_backend"):
             client2.app.state.openrouter_backend.available_models = ["model-a", "model-b"]
        _assert_app_state_matches_expected(client2, expected_state_values)


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

