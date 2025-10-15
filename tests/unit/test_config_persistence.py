from pathlib import Path

import pytest


@pytest.fixture
def functional_backend() -> str:
    """Provide a known functional backend for tests to use."""
    return "gemini"


from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
from src.core.common.exceptions import ConfigurationError, JSONParsingError
from src.core.config.app_config import load_config
from src.core.persistence import ConfigManager
from src.core.services.application_state_service import ApplicationStateService


@pytest.fixture(autouse=True)
def manage_env_vars(monkeypatch: pytest.MonkeyPatch):
    # Store original environment
    import os

    original_env = dict(os.environ)

    # Clear potentially polluting variables first
    env_vars_to_clear = [
        "DEFAULT_BACKEND",
        "LLM_BACKEND",
        "THINKING_BUDGET",
        "DISABLE_AUTH",
        "API_KEYS",
        "PYTEST_CURRENT_TEST",
        "PROXY_PORT",
        "COMMAND_PREFIX",
        "FORCE_CONTEXT_WINDOW",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)

    # Set clean test environment
    monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "test-proxy-key")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "dummy_or_key")
    monkeypatch.setenv("GEMINI_API_KEY_1", "dummy_gem_key")

    yield

    # Clean up numbered keys potentially set by other tests
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

    # Restore original environment completely
    os.environ.clear()
    os.environ.update(original_env)


def test_save_and_load_persistent_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    functional_backend: str,
    caplog: pytest.LogCaptureFixture,
):
    cfg_path = tmp_path / "cfg.yaml"
    # Ensure a clean slate for keys that might be set by other tests or global env
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "K")  # Use numbered keys for persistence
    monkeypatch.setenv("GEMINI_API_KEY_1", "G")
    monkeypatch.setenv("DEFAULT_BACKEND", "openrouter")
    app_config = load_config(str(cfg_path))
    app = build_app(config=app_config)
    caplog.set_level("WARNING")

    with TestClient(
        app
    ) as client:  # Auth headers not needed if client fixture handles it
        # Create a modified config with updated values (config is frozen, so we use model_copy)

        # Use model_copy to efficiently create updated configuration
        client_app = client.app  # type: ignore[attr-defined]
        app_config_state = client_app.state.app_config  # type: ignore[attr-defined]
        updated_failover_routes = dict(app_config_state.failover_routes)
        updated_failover_routes["r1"] = {
            "policy": "k",
            "elements": ["openrouter:model-a"],
        }

        updated_config = app_config_state.model_copy(
            update={
                "command_prefix": "$/",
                "backends": app_config_state.backends.model_copy(
                    update={"default_backend": functional_backend}
                ),
                "auth": app_config_state.auth.model_copy(
                    update={"redact_api_keys_in_prompts": False}
                ),
                "session": app_config_state.session.model_copy(
                    update={"default_interactive_mode": True}
                ),
                "failover_routes": updated_failover_routes,
            }
        )
        updated_config.save(cfg_path)  # type: ignore

    import yaml

    yaml_content = cfg_path.read_text()

    data = yaml.safe_load(cfg_path.read_text())
    assert data["backends"]["default_backend"] == functional_backend
    assert data["session"]["default_interactive_mode"] is True  # Updated path
    assert data["failover_routes"]["r1"]["elements"] == ["openrouter:model-a"]
    assert data["auth"]["redact_api_keys_in_prompts"] is False  # Updated path
    assert data["command_prefix"] == "$/"

    # Clear the environment variable that was set earlier to test config file loading
    monkeypatch.delenv("DEFAULT_BACKEND", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)

    from unittest.mock import patch

    with patch(
        "src.connectors.openrouter.OpenRouterBackend.get_available_models",
        return_value=["model-a"],
    ):
        try:
            app2_config = load_config(str(cfg_path))
        except Exception as e:
            # Print the actual validation error for debugging
            print("YAML content that failed validation:")
            print(yaml_content)
            print(f"Validation error type: {type(e).__name__}")
            print(f"Validation error message: {e}")
            if hasattr(e, "details") and "errors" in e.details:  # type: ignore
                print(f"Specific errors: {e.details['errors']}")  # type: ignore
            elif hasattr(e, "details"):  # type: ignore
                print(f"Error details: {e.details}")  # type: ignore
            raise
        app2 = build_app(config=app2_config)

    caplog.clear()

    with TestClient(app2) as client2:
        # Config file should be used since no CLI argument overrides it
        app2_state = client2.app.state  # type: ignore[attr-defined]
        assert app2_state.app_config.backends.default_backend == functional_backend
        assert app2_state.app_config.session.default_interactive_mode is True

        expected_elements = ["openrouter:model-a"]

        # The key 'r1' might not exist if all its elements were deemed unavailable.
        if "r1" in app2_state.app_config.failover_routes:
            assert (
                app2_state.app_config.failover_routes["r1"]["elements"]
                == expected_elements
            )
        else:
            assert (
                not expected_elements
            )  # If no "r1" route, expected_elements should be empty


def test_invalid_persisted_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, functional_backend: str
):
    cfg_path = tmp_path / "cfg.yaml"
    # Persist an invalid default_backend
    import yaml

    invalid_cfg_data = {"backends": {"default_backend": "non_existent_backend"}}
    cfg_path.write_text(yaml.safe_dump(invalid_cfg_data))

    # Ensure no functional backends are accidentally configured via env that might match
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv(
        "OPENROUTER_API_KEY_1", "K_temp"
    )  # Ensure some backend could be functional
    monkeypatch.setenv("DEFAULT_BACKEND", "non_existent_backend")
    monkeypatch.setenv("LLM_BACKEND", "non_existent_backend")

    # In the new architecture, invalid backends are not validated at config load time
    # They are simply loaded as-is, and the application will use a fallback if needed
    app_config = load_config(str(cfg_path))
    assert app_config.backends.default_backend == "non_existent_backend"

    app = build_app(config=app_config)

    # The app should build successfully even with an invalid default backend
    with TestClient(app) as client:
        assert (
            client.app.state.app_config.backends.default_backend  # type: ignore
            == "non_existent_backend"
        )

    monkeypatch.delenv("OPENROUTER_API_KEY_1", raising=False)  # Clean up
    monkeypatch.delenv("DEFAULT_BACKEND", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)


def test_load_rejects_non_object_json(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text("[]", encoding="utf-8")

    manager = ConfigManager(FastAPI(), str(cfg_path))

    with pytest.raises(ConfigurationError) as exc_info:
        manager.load()

    assert "JSON object" in str(exc_info.value)


pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


def test_apply_default_backend_invalid_backend_raises_configuration_error() -> None:
    app = FastAPI()
    application_state = ApplicationStateService()
    manager = ConfigManager(
        app,
        path=":memory:",
        app_state=application_state,
    )

    with pytest.raises(ConfigurationError) as exc_info:
        manager._apply_default_backend("nonexistent")

    assert exc_info.value.details == {
        "backend": "nonexistent",
        "functional_backends": [],
    }


def test_apply_default_backend_invalid_backend_still_raises_with_cli_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    application_state = ApplicationStateService()
    manager = ConfigManager(
        app,
        path=":memory:",
        app_state=application_state,
    )

    monkeypatch.setenv("LLM_BACKEND", "openai")

    with pytest.raises(ConfigurationError) as exc_info:
        manager._apply_default_backend("nonexistent")

    assert exc_info.value.details == {
        "backend": "nonexistent",
        "functional_backends": [],
    }


def test_load_raises_json_parsing_error_for_invalid_json(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{not: valid json}")

    app = FastAPI()
    manager = ConfigManager(app, path=str(cfg_path))

    with pytest.raises(JSONParsingError) as exc_info:
        manager.load()

    assert "Failed to parse config file" in str(exc_info.value)
