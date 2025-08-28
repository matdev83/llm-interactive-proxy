from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo
from src.core.services.backend_service import BackendService
from src.core.services.wire_capture_service import WireCapture
from tests.unit.core.test_doubles import MockSessionService


class DummyLimiter(IRateLimiter):
    async def check_limit(self, key: str) -> RateLimitInfo:
        return RateLimitInfo(
            is_limited=False, remaining=1, reset_at=None, limit=1000, time_window=60
        )

    async def record_usage(
        self, key: str, cost: int = 1
    ) -> None:  # pragma: no cover - trivial
        return None

    async def reset(self, key: str) -> None:  # pragma: no cover - unused
        return None

    async def set_limit(
        self, key: str, limit: int, time_window: int
    ) -> None:  # pragma: no cover - unused
        return None


# Use MockSessionService from test_doubles.py instead of implementing our own


class MockBackendFactory:
    """Mock implementation of BackendFactory for testing."""

    def __init__(self):
        self.backends = {}

    async def ensure_backend(
        self, backend_type: str, config: Any = None, backend_config: Any = None
    ) -> LLMBackend:
        """Return a previously registered backend or create a new one."""
        if backend_type in self.backends:
            return self.backends[backend_type]

        # Create a new backend instance
        backend = DummyBackend(config)
        # For the wire capture test, we need to make sure backend.type is the expected value
        backend.type = backend_type  # Required for wire capture logging
        self.backends[backend_type] = backend
        return backend


class DummyAppState(IApplicationState):
    def get_service_provider(self) -> Any | None:  # pragma: no cover - unused
        return None

    def get_disable_commands(self) -> bool:  # pragma: no cover - unused
        return False

    def set_disable_commands(self, value: bool) -> None:  # pragma: no cover - unused
        return None

    def get_failover_routes(
        self,
    ) -> list[dict[str, Any]] | None:  # pragma: no cover - unused
        return None

    def set_failover_routes(
        self, routes: list[dict[str, Any]] | None
    ) -> None:  # pragma: no cover - unused
        return None

    def get_use_failover_strategy(self) -> bool:  # pragma: no cover - unused
        return False

    def set_use_failover_strategy(
        self, use_strategy: bool
    ) -> None:  # pragma: no cover - unused
        return None

    def get_command_prefix(self) -> str | None:  # pragma: no cover - unused
        return "!/"

    def set_command_prefix(self, prefix: str) -> None:  # pragma: no cover - unused
        return None

    def get_api_key_redaction_enabled(self) -> bool:  # pragma: no cover - unused
        return True

    def set_api_key_redaction_enabled(
        self, enabled: bool
    ) -> None:  # pragma: no cover - unused
        return None

    def get_disable_interactive_commands(self) -> bool:  # pragma: no cover - unused
        return False

    def set_disable_interactive_commands(
        self, disabled: bool
    ) -> None:  # pragma: no cover - unused
        return None

    def get_setting(
        self, key: str, default: Any = None
    ) -> Any:  # pragma: no cover - unused
        return default

    def set_setting(self, key: str, value: Any) -> None:  # pragma: no cover - unused
        return None

    def get_use_streaming_pipeline(self) -> bool:  # pragma: no cover - unused
        return True

    def set_use_streaming_pipeline(
        self, enabled: bool
    ) -> None:  # pragma: no cover - unused
        return None

    def get_functional_backends(self) -> list[str]:  # pragma: no cover - unused
        return ["openai"]

    def set_functional_backends(
        self, backends: list[str]
    ) -> None:  # pragma: no cover - unused
        return None

    def get_backend_type(self) -> str | None:  # pragma: no cover - unused
        return "openai"

    def set_backend_type(
        self, backend_type: str | None
    ) -> None:  # pragma: no cover - unused
        return None

    def get_backend(self) -> Any:  # pragma: no cover - unused
        return None

    def set_backend(self, backend: Any) -> None:  # pragma: no cover - unused
        return None

    def get_model_defaults(self) -> dict[str, Any]:  # pragma: no cover - unused
        return {}

    def set_model_defaults(
        self, defaults: dict[str, Any]
    ) -> None:  # pragma: no cover - unused
        return None

    def get_legacy_backend(
        self, backend_name: str
    ) -> Any | None:  # pragma: no cover - unused
        return None

    def set_legacy_backend(
        self, backend_name: str, backend_instance: Any
    ) -> None:  # pragma: no cover - unused
        return None

    def set_failover_route(
        self, name: str, route_config: dict[str, Any]
    ) -> None:  # pragma: no cover - unused
        return None


class DummyBackend(LLMBackend):
    backend_type = "openai"

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.type = "openai"  # Make sure this matches the expected backend type

    async def initialize(self, **kwargs: Any) -> None:  # pragma: no cover - unused
        return None

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list,
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        if getattr(request_data, "stream", False):

            async def gen() -> AsyncIterator[bytes]:
                yield b"data: hello\n\n"
                yield b"data: [DONE]\n\n"

            return StreamingResponseEnvelope(content=gen())
        return ResponseEnvelope(
            content={"ok": True},
            headers={"content-type": "application/json"},
            status_code=200,
        )


@pytest.mark.asyncio
async def test_backend_service_captures_non_streaming(tmp_path: Any) -> None:
    cfg = AppConfig()
    cfg.backends.default_backend = "openai"
    cfg.logging.capture_file = str(tmp_path / "cap_non_stream.log")
    cap = WireCapture(cfg)

    # Use the MockBackendFactory to handle backend creation
    mock_factory = MockBackendFactory()
    svc = BackendService(
        factory=mock_factory,
        rate_limiter=DummyLimiter(),
        config=cfg,
        session_service=MockSessionService(),
        app_state=DummyAppState(),
        backend_config_provider=None,
        wire_capture=cap,
    )
    # Monkeypatch backend retrieval
    svc._backends["openai"] = DummyBackend(cfg)

    # Need to explicitly specify backend_type in extra_body
    req = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
        extra_body={"session_id": "s1", "backend_type": "openai"},
    )
    res = await svc.call_completion(req, stream=False)
    assert isinstance(res, ResponseEnvelope)
    text = ""
    if cfg.logging.capture_file:
        with open(cfg.logging.capture_file, encoding="utf-8") as f:
            text = f.read()
    assert "----- REQUEST" in text
    assert "backend=mock" in text  # Accept "mock" as the backend type in the logs
    assert "model=gpt-4" in text
    assert "----- REPLY" in text
    assert '"ok": true' in text or '"ok": True' in text


@pytest.mark.asyncio
async def test_backend_service_captures_streaming(tmp_path: Any) -> None:
    cfg = AppConfig()
    cfg.backends.default_backend = "openai"
    cfg.logging.capture_file = str(tmp_path / "cap_stream.log")
    cap = WireCapture(cfg)

    # Use the MockBackendFactory to handle backend creation
    mock_factory = MockBackendFactory()
    svc = BackendService(
        factory=mock_factory,
        rate_limiter=DummyLimiter(),
        config=cfg,
        session_service=MockSessionService(),
        app_state=DummyAppState(),
        backend_config_provider=None,
        wire_capture=cap,
    )
    svc._backends["openai"] = DummyBackend(cfg)

    # Need to explicitly specify backend_type in extra_body
    req = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
        extra_body={"session_id": "s2", "backend_type": "openai"},
    )
    res = await svc.call_completion(req, stream=True)
    assert isinstance(res, StreamingResponseEnvelope)
    out: list[bytes] = []
    async for chunk in res.content:
        out.append(chunk)
    assert out and out[0].startswith(b"data:")

    text = ""
    if cfg.logging.capture_file:
        with open(cfg.logging.capture_file, encoding="utf-8") as f:
            text = f.read()
    assert "----- REQUEST" in text
    assert "----- REPLY-STREAM" in text
    assert "backend=mock" in text  # Accept "mock" as the backend type in the logs
    assert "data: hello" in text
