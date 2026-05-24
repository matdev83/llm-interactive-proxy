import json
import os
import socket
import subprocess
import sys
import time

import pytest
from freezegun import freeze_time

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
]  # Requires real network calls


@pytest.fixture(scope="session", autouse=True)
def check_gemini_key():
    """Check for Gemini API keys using the configuration system."""
    try:
        from src.core.config import _collect_api_keys

        gemini_keys = _collect_api_keys("GEMINI_API_KEY")
        if not gemini_keys:
            pytest.skip(
                "Gemini API key not found in environment variables (GEMINI_API_KEY or GEMINI_API_KEY_1)"
            )
    except ImportError:
        # Fallback to direct environment variable check if config system is not available
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY_1")):
            pytest.skip(
                "Gemini API key not found in environment variables (GEMINI_API_KEY or GEMINI_API_KEY_1)"
            )


@pytest.fixture(autouse=True)
def patch_backend_discovery():
    # Override the autouse fixture from tests.conftest - we want real network calls
    yield


# Ensure the commented out version is not present if it was part of an error
# from tests.conftest import ORIG_GEMINI_KEY as ORIG_KEY


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # Ensure only Gemini is functional for these end-to-end tests
    monkeypatch.setenv("LLM_BACKEND", "gemini")

    gemini_api_key = os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY")
    if gemini_api_key:
        monkeypatch.setenv("GEMINI_API_KEY", gemini_api_key)

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    yield


def _wait_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0) -> None:
    # Use freezegun to control time progression instead of sleeping
    with freeze_time() as frozen_time:
        end = time.time() + timeout
        while time.time() < end:
            try:
                with socket.create_connection((host, port), timeout=1):
                    return
            except OSError:
                # Advance time instead of sleeping
                frozen_time.tick(delta=0.1)
    raise RuntimeError("server did not start")


def _run_client(cfg_path: str, port: int) -> str:
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "dummy")
    gemini_api_key = os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY")
    if gemini_api_key:
        env["GEMINI_API_KEY"] = gemini_api_key
        env["GEMINI_API_KEY_1"] = gemini_api_key
    result = subprocess.run(
        [sys.executable, os.path.join("dev", "test_client.py"), cfg_path],
        text=True,
        env=env,
        capture_output=True,
    )
    return result.stdout + result.stderr


def _start_server() -> tuple[subprocess.Popen, int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])

    # Pass the Gemini API key to the uvicorn server process
    server_env = os.environ.copy()
    gemini_api_key = os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY")
    if gemini_api_key:
        server_env["GEMINI_API_KEY"] = gemini_api_key

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.core.app.application_factory:build_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _wait_port(port)
    return proc, port


def _stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _has_gemini_api_key() -> bool:
    """Check if Gemini API keys are available using the configuration resolution mechanism."""
    try:
        from src.core.config import _collect_api_keys

        gemini_keys = _collect_api_keys("GEMINI_API_KEY")
        return bool(gemini_keys)
    except ImportError:
        # Fallback to direct environment variable check if config system is not available
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY_1"))


MODEL = "gemini-2.0-flash-lite-preview-02-05"


@pytest.mark.skipif(
    lambda: not _has_gemini_api_key(),
    reason="Gemini API key not found using configuration resolution mechanism",
)
def test_gemini_basic(tmp_path):
    server, port = _start_server()
    try:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps(
                {
                    "api_base": f"http://127.0.0.1:{port}/v1",
                    "model": MODEL,
                    "prompts": ["Hello"],
                }
            )
        )
        out = _run_client(str(cfg), port)
        assert out.strip()
    finally:
        _stop_server(server)


@pytest.mark.skipif(
    lambda: not _has_gemini_api_key(),
    reason="Gemini API key not found using configuration resolution mechanism",
)
def test_gemini_interactive_banner(tmp_path):
    server, port = _start_server()
    try:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps(
                {
                    "api_base": f"http://127.0.0.1:{port}/v1",
                    "model": MODEL,
                    "prompts": ["Hello"],
                }
            )
        )
        out = _run_client(str(cfg), port)
        assert "Hello, this is" in out
    finally:
        _stop_server(server)
