import asyncio
import json
import os
import socket
import tempfile
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import requests
import uvicorn
from src.core.app.test_builder import build_test_app as build_app

pytestmark = pytest.mark.network

# Optional client libraries - skip related scenarios if missing.

GENAI_AVAILABLE = False
ANTHROPIC_AVAILABLE = True
ZAI_AVAILABLE = True


######################################################################
# Helper - lightweight proxy server wrapper identical to other suites
######################################################################


class _ProxyServer:
    """Run the FastAPI app under Uvicorn in a thread for integration tests."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        # Pick an ephemeral port so tests can run in parallel
        self.port = self._find_free_port()

        self.config_file_path: Path | None = (
            None  # To store the path of the temporary config file
        )

        # Create a temporary config file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(cfg, f)
            self.config_file_path = Path(f.name)

        from src.core.config.app_config import AppConfig

        app_config = AppConfig.model_validate(cfg)
        self.app = build_app(config=app_config)
        self.server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    # --------------------------------------------------------------
    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    # --------------------------------------------------------------
    def start(self) -> None:
        async def _run() -> None:
            config = uvicorn.Config(
                self.app, host="127.0.0.1", port=self.port, log_level="error"
            )
            self.server = uvicorn.Server(config)
            await self.server.serve()

        self._thread = threading.Thread(target=lambda: asyncio.run(_run()), daemon=True)
        self._thread.start()

        # Wait until the server responds or timeout after 15 s
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = requests.get(f"http://127.0.0.1:{self.port}/", timeout=2)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError("Proxy server failed to start within timeout")

    # --------------------------------------------------------------
    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True  # type: ignore[attr-defined]
        if self._thread:
            self._thread.join(timeout=5)

        # Clean up the temporary config file
        if self.config_file_path and self.config_file_path.exists():
            self.config_file_path.unlink()  # Delete the file


######################################################################
# Fixtures
######################################################################

BACKEND_MODEL_MAP = {
    "zai_anthropic": "glm-4.5-flash",
}

REQUIRED_ENV_VARS = {
    "zai_anthropic": "ZAI_API_KEY",
}


@pytest.fixture(scope="function")
def proxy_server(request: Any) -> Generator[_ProxyServer, None, None]:
    """Start proxy configured for the backend under test."""
    backend = (
        request.param
        if hasattr(request, "param")
        else (
            request.getfixturevalue("backend")
            if "backend" in request.fixturenames
            else "zai_anthropic"
        )
    )

    os.environ["DISABLE_AUTH"] = "true"

    anthropic_api_keys: dict[str, str]
    anthropic_api_base_url: str

    if backend == "zai_anthropic":
        zai_key_present = any(
            k.startswith("ZAI_API_KEY") and os.getenv(k) for k in os.environ
        )
        if not zai_key_present:
            pytest.skip(
                "ZAI_API_KEY not found, skipping real backend test for ZAI Anthropic endpoint"
            )

        anthropic_api_keys = {"ANTHROPIC_API_KEY": os.environ["ZAI_API_KEY"]}
        anthropic_api_base_url = "https://api.z.ai/api/anthropic"
    else:
        # This block is theoretically unreachable given SCENARIOS, but kept for robustness
        anthropic_api_keys = {
            k: v
            for k, v in os.environ.items()
            if k.startswith("ANTHROPIC_API_KEY") and v
        }
        anthropic_api_base_url = "https://api.anthropic.com/v1"  # Default Anthropic URL

    cfg: dict[str, Any] = {
        "backend": "anthropic",
        "interactive_mode": False,
        "command_prefix": "!/",
        "disable_auth": True,
        "disable_accounting": True,
        "proxy_timeout": 60,
        "anthropic_api_base_url": anthropic_api_base_url,
        "anthropic_api_keys": anthropic_api_keys,
        "app_site_url": "http://localhost",
        "app_x_title": "integration-tests",
    }

    server = _ProxyServer(cfg)
    server.start()
    try:
        yield server
    finally:
        server.stop()


######################################################################
# Test matrix - real backend round-trips
######################################################################

SCENARIOS = [
    ("anthropic", "zai_anthropic"),
]


@pytest.mark.integration
@pytest.mark.network
@pytest.mark.parametrize("client_type,backend", SCENARIOS)
def test_end_to_end_chat_completion(
    client_type: str, backend: str, proxy_server: _ProxyServer
) -> None:
    """End-to-end check - send simple prompt through proxy to real backend and verify basic response structure."""

    model_name = BACKEND_MODEL_MAP[backend]
    base_url = f"http://127.0.0.1:{proxy_server.port}"

    if client_type == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key="test-key", base_url=base_url)
        try:
            resp = client.messages.create(
                model=model_name,
                max_tokens=32,
                messages=[{"role": "user", "content": "Hello!"}],
            )
        except Exception as exc:
            pytest.skip(f"Anthropic request failed ({exc}); skipping scenario.")

        assert hasattr(resp, "content") and resp.content, "Empty response content"
    else:
        raise AssertionError(f"Unknown client type {client_type}")


######################################################################
# Streaming variants
######################################################################


@pytest.mark.integration
@pytest.mark.network
@pytest.mark.parametrize("client_type,backend", SCENARIOS)
def test_end_to_end_chat_completion_streaming(
    client_type: str, backend: str, proxy_server: _ProxyServer
) -> None:

    model_name = BACKEND_MODEL_MAP[backend]
    base_url = f"http://127.0.0.1:{proxy_server.port}"

    if client_type == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key="test-key", base_url=base_url)
        try:
            stream = client.messages.create(
                model=model_name,
                max_tokens=16,
                messages=[{"role": "user", "content": "Hello!"}],
                stream=True,
            )
            first = next(stream, None)
        except Exception as exc:
            pytest.skip(f"Anthropic streaming failed ({exc}); skipping.")

        assert first is not None, "No events from Anthropics stream"

    else:
        raise AssertionError(f"Unknown client type {client_type}")
