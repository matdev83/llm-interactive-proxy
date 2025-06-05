import os
from src import main as app_main


def test_apply_cli_args_sets_env(monkeypatch):
    args = app_main.parse_cli_args([
        "--backend",
        "gemini",
        "--gemini-api-key",
        "TESTKEY",
        "--port",
        "1234",
        "--command-prefix",
        "$/",
    ])
    cfg = app_main.apply_cli_args(args)
    assert os.environ["LLM_BACKEND"] == "gemini"
    assert os.environ["GEMINI_API_KEY"] == "TESTKEY"
    assert os.environ["PROXY_PORT"] == "1234"
    assert os.environ["COMMAND_PREFIX"] == "$/"
    assert cfg["backend"] == "gemini"
    assert cfg["proxy_port"] == 1234
    assert cfg["command_prefix"] == "$/"


def test_build_app_uses_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "KEY")
    monkeypatch.setenv("COMMAND_PREFIX", "??/")
    app = app_main.build_app()
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        assert client.app.state.backend_type == "gemini"
        assert hasattr(client.app.state, "gemini_backend")
        assert client.app.state.command_prefix == "??/"
