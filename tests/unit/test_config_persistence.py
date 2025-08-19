import json

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
from src.core.config.app_config import load_config


@pytest.fixture(autouse=True)
def manage_env_vars(monkeypatch):
    monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "test-proxy-key")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "dummy_or_key")
    monkeypatch.setenv("GEMINI_API_KEY_1", "dummy_gem_key")
    yield
    for i in range(1, 21):  # Clean up numbered keys potentially set by other tests
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)


def test_save_and_load_persistent_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.json"
    # Ensure a clean slate for keys that might be set by other tests or global env
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "K")  # Use numbered keys for persistence
    monkeypatch.setenv("GEMINI_API_KEY_1", "G")
    monkeypatch.setenv("DEFAULT_BACKEND", "openrouter")
    app_config = load_config(str(cfg_path))
    app = build_app(config=app_config)
    with TestClient(
        app
    ) as client:  # Auth headers not needed if client fixture handles it
        client.app.state.app_config.failover_routes["r1"] = {
            "policy": "k",
            "elements": ["openrouter:model-a"],
        }
        client.app.state.app_config.session.default_interactive_mode = True
        client.app.state.app_config.backends.default_backend = (
            "gemini"  # This is the runtime state
        )
        client.app.state.app_config.auth.redact_api_keys_in_prompts = False
        client.app.state.app_config.command_prefix = "$/"
        client.app.state.app_config.save(cfg_path)

    data = json.loads(cfg_path.read_text())
    assert data["backends"]["default_backend"] == "gemini"
    assert data["session"]["default_interactive_mode"] is True  # Updated path
    assert data["failover_routes"]["r1"]["elements"] == ["openrouter:model-a"]
    assert data["auth"]["redact_api_keys_in_prompts"] is False  # Updated path
    assert data["command_prefix"] == "$/"

    # Clear the environment variable that was set earlier to test config file loading
    monkeypatch.delenv("DEFAULT_BACKEND", raising=False)

    from unittest.mock import patch

    with patch(
        "src.connectors.openrouter.OpenRouterBackend.get_available_models",
        return_value=["model-a"],
    ):
        app2_config = load_config(str(cfg_path))
        app2 = build_app(config=app2_config)

    with TestClient(app2) as client2:
        # Config file (default_backend=gemini) should be used since no CLI argument overrides it
        assert client2.app.state.app_config.backends.default_backend == "gemini"
        assert client2.app.state.app_config.session.default_interactive_mode is True

        expected_elements = ["openrouter:model-a"]

        # The key 'r1' might not exist if all its elements were deemed unavailable.
        if "r1" in client2.app.state.app_config.failover_routes:  # Updated path
            assert (
                client2.app.state.app_config.failover_routes["r1"]["elements"]
                == expected_elements  # Updated path
            )
        else:
            assert (
                not expected_elements
            )  # If no "r1" route, expected_elements should be empty


def test_invalid_persisted_backend(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.json"
    # Persist an invalid default_backend
    invalid_cfg_data = {"backends": {"default_backend": "non_existent_backend"}}
    cfg_path.write_text(json.dumps(invalid_cfg_data))

    # Ensure no functional backends are accidentally configured via env that might match
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv(
        "OPENROUTER_API_KEY_1", "K_temp"
    )  # Ensure some backend could be functional

    # In the new architecture, invalid backends are not validated at config load time
    # They are simply loaded as-is, and the application will use a fallback if needed
    app_config = load_config(str(cfg_path))
    app = build_app(config=app_config)

    # The app should build successfully even with an invalid default backend
    with TestClient(app) as client:
        # The invalid backend should be loaded but won't be functional
        assert (
            client.app.state.app_config.backends.default_backend
            == "non_existent_backend"
        )
        # In the new architecture, functional_backends is determined at runtime
        # and not stored directly on the config, so we'll just verify the app loaded
        assert client.app.state.app_config is not None

    monkeypatch.delenv("OPENROUTER_API_KEY_1", raising=False)  # Clean up
