import json
import os
import random
import socket
import subprocess
import sys
import time

import pytest


@pytest.fixture(autouse=True)
def patch_backend_discovery():
    # Override the autouse fixture from tests.conftest - we want real network calls
    yield


from tests.conftest import ORIG_GEMINI_KEY as ORIG_KEY


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    if ORIG_KEY:
        monkeypatch.setenv("GEMINI_API_KEY_1", ORIG_KEY)
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


def _start_server(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    proc = subprocess.Popen(
        [
            "uvicorn",
            "src.main:build_app",
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
    return proc


def _stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


MODEL = "gemini-2.0-flash-lite-preview-02-05"


def test_gemini_basic(tmp_path):
    port = random.randint(8100, 8200)
    assert os.getenv("GEMINI_API_KEY_1"), "GEMINI_API_KEY_1 missing"
    server = _start_server(port)
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
    port = random.randint(8201, 8300)
    assert os.getenv("GEMINI_API_KEY_1"), "GEMINI_API_KEY_1 missing"
    server = _start_server(port)
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
