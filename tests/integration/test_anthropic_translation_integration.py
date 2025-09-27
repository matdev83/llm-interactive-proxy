import asyncio
import json
import os
import socket
import tempfile
import threading
import time
import warnings as _warnings
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import requests
from src.core.app.test_builder import build_httpx_mock_test_app as build_app

# Suppress upstream deprecations emitted during uvicorn/websockets import
_warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*websockets\.legacy is deprecated.*",
)
_warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*websockets\.server\.WebSocketServerProtocol is deprecated.*",
)

import uvicorn

# Suppress Windows ProactorEventLoop and upstream websockets deprecations for this module
pytestmark = [
    pytest.mark.filterwarnings(
        "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
    ),
    pytest.mark.filterwarnings(
        "ignore:.*websockets\\.legacy is deprecated.*:DeprecationWarning"
    ),
    pytest.mark.filterwarnings(
        "ignore:.*websockets\\.server\\.WebSocketServerProtocol is deprecated.*:DeprecationWarning"
    ),
]


class _ProxyServer:
    """Run the FastAPI app under Uvicorn in a thread for integration tests."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.port = self._find_free_port()
        self.config_file_path: Path | None = None
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(cfg, f)
            self.config_file_path = Path(f.name)

        from src.core.config.app_config import AppConfig

        app_config = AppConfig.model_validate(cfg)
        self.app = build_app(config=app_config)
        self.server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def start(self) -> None:
        async def _run() -> None:
            config = uvicorn.Config(
                self.app, host="127.0.0.1", port=self.port, log_level="error"
            )
            self.server = uvicorn.Server(config)
            await self.server.serve()

        self._thread = threading.Thread(target=lambda: asyncio.run(_run()), daemon=True)
        self._thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = requests.get(f"http://127.0.0.1:{self.port}/docs", timeout=2)
                if r.status_code == 200:
                    return
            except requests.exceptions.ConnectionError:
                pass
            time.sleep(0.25)
        raise RuntimeError("Proxy server failed to start within timeout")

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True  # type: ignore[attr-defined]
        if self._thread:
            self._thread.join(timeout=5)
        if self.config_file_path and self.config_file_path.exists():
            self.config_file_path.unlink()


@pytest.fixture(scope="function")
def proxy_server(request: Any) -> Generator[_ProxyServer, None, None]:
    """Start proxy configured for the backend under test."""
    os.environ["DISABLE_AUTH"] = "true"
    cfg: dict[str, Any] = {
        "backend": "anthropic",
        "interactive_mode": False,
        "command_prefix": "!/",
        "disable_auth": True,
        "disable_accounting": True,
        "proxy_timeout": 60,
        "anthropic_api_base_url": "https://api.anthropic.com/v1",
        "anthropic_api_keys": {"ANTHROPIC_API_KEY": "test-key"},
        "app_site_url": "http://localhost",
        "app_x_title": "integration-tests",
    }

    server = _ProxyServer(cfg)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.mark.integration
def test_anthropic_multimodal_translation(
    proxy_server: _ProxyServer, mocker: Any
) -> None:
    """Verify that a multimodal request is correctly translated to the Anthropic format."""
    import warnings

    # Uvicorn imports deprecated WebSocketServerProtocol from websockets.server
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r".*websockets\.server\.WebSocketServerProtocol is deprecated.*",
    )

    # Upstream websockets.legacy deprecation warning (triggered by anthropic dependency)
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r".*websockets\.legacy is deprecated.*",
    )

    from anthropic import Anthropic
    from anthropic.types import Message, TextBlock, Usage

    # Mock the response from the Anthropic API
    mock_response = Message(
        id="msg_01A0QnE4S7rD8nSW2C9d9gM1",
        type="message",
        role="assistant",
        model="claude-3-haiku-20240307",
        content=[TextBlock(type="text", text="This is a test response.")],
        stop_reason="end_turn",
        usage=Usage(input_tokens=10, output_tokens=25),
    )
    mocker.patch(
        "anthropic.resources.messages.Messages.create", return_value=mock_response
    )

    client = Anthropic(
        api_key="test-key", base_url=f"http://127.0.0.1:{proxy_server.port}"
    )

    resp = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=32,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
                        },
                    },
                ],
            }
        ],
    )

    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == "This is a test response."
