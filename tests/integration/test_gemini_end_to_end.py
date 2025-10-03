import json
import os
import socket
import subprocess
import sys
import time

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
]  # Requires real network calls

ORIG_KEY = os.getenv("GEMINI_API_KEY_1")


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
    if ORIG_KEY:  # ORIG_KEY is now defined due to the import above
        monkeypatch.setenv("GEMINI_API_KEY_1", ORIG_KEY)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    yield


def _wait_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def _run_client(cfg_path: str, port: int) -> str:
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "dummy")
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

    env = os.environ.copy()
    env["DISABLE_AUTH"] = "true"  # Disable authentication for tests
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    _wait_port(port)
    return proc, port


def _stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


MODEL = "gemini-2.0-flash-lite-preview-02-05"


def test_gemini_basic(tmp_path):
    assert os.getenv("GEMINI_API_KEY_1"), "GEMINI_API_KEY_1 missing"
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


def test_gemini_interactive_banner(tmp_path):
    assert os.getenv("GEMINI_API_KEY_1"), "GEMINI_API_KEY_1 missing"
    server, port = _start_server()
    try:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps(
                {
                    "api_base": f"http://127.0.0.1:{port}/v1",
                    "model": MODEL,
                    "prompts": ["!/set(interactive=True)", "Hello"],
                }
            )
        )
        out = _run_client(str(cfg), port)
        assert "Hello, this is" in out
    finally:
        _stop_server(server)
