import os
import pytest
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.cli import parse_cli_args, apply_cli_args
from src.main import build_app as app_main_build_app # Import build_app from main.py


def test_apply_cli_args_sets_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(
        [
            "--default-backend",
            "gemini",
            "--gemini-api-key",
            "TESTKEY",
            "--port",
            "1234",
            "--command-prefix",
            "$/",
        ]
    )
    cfg = apply_cli_args(args)
    assert os.environ["LLM_BACKEND"] == "gemini"
    assert os.environ["GEMINI_API_KEY"] == "TESTKEY"
    assert os.environ["PROXY_PORT"] == "1234"
    assert os.environ["COMMAND_PREFIX"] == "$/"
    assert cfg["backend"] == "gemini"
    assert cfg["gemini_api_keys"] == {"GEMINI_API_KEY": "TESTKEY"}
    assert cfg["proxy_port"] == 1234
    assert cfg["command_prefix"] == "$/"
    # cleanup environment variables set by apply_cli_args
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("PROXY_PORT", raising=False)
    monkeypatch.delenv("COMMAND_PREFIX", raising=False)


def test_cli_interactive_mode(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_MODE", raising=False)


def test_cli_redaction_flag(monkeypatch):
    monkeypatch.delenv("REDACT_API_KEYS_IN_PROMPTS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(["--disable-redact-api-keys-in-prompts"])
    cfg = apply_cli_args(args)
    assert os.environ["REDACT_API_KEYS_IN_PROMPTS"] == "false"
    assert cfg["redact_api_keys_in_prompts"] is False
    monkeypatch.delenv("REDACT_API_KEYS_IN_PROMPTS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(["--interactive-mode"])
    cfg = apply_cli_args(args)
    assert os.environ["INTERACTIVE_MODE"] == "True"
    assert cfg["interactive_mode"] is True
    monkeypatch.delenv("INTERACTIVE_MODE", raising=False)


def test_build_app_uses_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("LLM_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "KEY")
    monkeypatch.setenv("COMMAND_PREFIX", "??/")
    app = app_main_build_app()
    from fastapi.testclient import TestClient

    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        assert client.app.state.backend_type == "gemini"
        assert hasattr(client.app.state, "gemini_backend")
        assert client.app.state.command_prefix == "??/"


def test_build_app_uses_interactive_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("INTERACTIVE_MODE", "true")
    monkeypatch.setenv("LLM_BACKEND", "openrouter") # Add this line
    app = app_main_build_app()
    from fastapi.testclient import TestClient

    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        session = client.app.state.session_manager.get_session("s1")  # type: ignore
        assert session.proxy_state.interactive_mode is True


def test_default_command_prefix_from_env(monkeypatch):
    monkeypatch.delenv("COMMAND_PREFIX", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    args = parse_cli_args([])
    cfg = apply_cli_args(args)
    assert cfg["command_prefix"] == DEFAULT_COMMAND_PREFIX

def test_check_privileges_root(monkeypatch):
    from src.core.cli import _check_privileges
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    with pytest.raises(SystemExit):
        _check_privileges()

def test_check_privileges_non_root(monkeypatch):
    from src.core.cli import _check_privileges
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    _check_privileges()
