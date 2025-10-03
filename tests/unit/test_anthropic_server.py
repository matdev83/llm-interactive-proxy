from __future__ import annotations

import asyncio
from typing import Any

import pytest
from src.anthropic_server import create_anthropic_app, main
from src.core.config.app_config import AppConfig, LogLevel


def test_create_anthropic_app_registers_endpoints() -> None:
    cfg = AppConfig()
    app = create_anthropic_app(cfg)

    # App should be created and configured
    assert app is not None
    assert hasattr(app.state, "app_config")

    # Ensure key Anthropic endpoints exist without prefix
    paths = {route.path for route in app.router.routes}  # type: ignore[attr-defined]
    assert "/v1/messages" in paths
    assert "/v1/models" in paths
    assert "/v1/health" in paths
    assert "/v1/info" in paths


@pytest.mark.asyncio
async def test_main_raises_when_port_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Provide a config with no anthropic_port to trigger the error path
    cfg = AppConfig()
    cfg.anthropic_port = None

    monkeypatch.setattr("src.anthropic_server.AppConfig.from_env", lambda: cfg)

    with pytest.raises(ValueError):
        await main()


@pytest.mark.asyncio
async def test_main_starts_server_when_port_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Build a minimal valid config
    cfg = AppConfig()
    cfg.anthropic_port = 9100
    cfg.host = "127.0.0.1"
    cfg.logging.level = LogLevel.ERROR

    monkeypatch.setattr("src.anthropic_server.AppConfig.from_env", lambda: cfg)

    # Stub uvicorn.Server to avoid actually starting a server
    class DummyServer:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.served = False

        async def serve(self) -> None:
            # Simulate a quick startup/shutdown cycle
            await asyncio.sleep(0)
            self.served = True

    # Replace Server class used in anthropic_server
    monkeypatch.setattr("src.anthropic_server.uvicorn.Server", DummyServer)  # type: ignore[attr-defined]

    # Run main; should complete without raising
    await main()


# Suppress Windows ProactorEventLoop warnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
