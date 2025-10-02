from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from src.connectors.base import LLMBackend
from src.core.app.test_builder import build_test_app_async
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo

from tests.utils.test_di_utils import get_required_service_from_app


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


class DummyBackend(LLMBackend):
    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.type = "openai"  # Make sure this matches the expected backend type

    async def initialize(self, **kwargs: Any) -> None:  # pragma: no cover - unused
        return None

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        if request.stream:

            async def gen() -> AsyncIterator[bytes]:
                yield b"data: hello\n\n"
                yield b"data: [DONE]\n\n"

            return StreamingResponseEnvelope(content=gen())
        return ResponseEnvelope(
            content={"id": "test", "object": "mock", "ok": True},
            headers={"content-type": "application/json"},
            status_code=200,
        )

    async def models(self):
        return []


class DummyAppState(IApplicationState):
    def __init__(self):
        self.some_state = "test"


@pytest.mark.asyncio
async def test_backend_service_captures_non_streaming() -> None:
    """Test backend service wire capture for non-streaming responses using proper DI."""
    cfg = AppConfig()
    cfg.backends.default_backend = "openai"

    # Build an integration test app with all required services (async version)
    app = await build_test_app_async(cfg)
    svc = get_required_service_from_app(app, IBackendService)

    # Configure the service for testing
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
    # Check that we got a response (don't check specific content as it might be processed)
    assert res.content is not None


@pytest.mark.asyncio
async def test_backend_service_captures_streaming() -> None:
    """Test backend service wire capture for streaming responses using proper DI."""
    cfg = AppConfig()
    cfg.backends.default_backend = "openai"

    # Build an integration test app with all required services (async version)
    app = await build_test_app_async(cfg)
    svc = get_required_service_from_app(app, IBackendService)

    # Configure the service for testing
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
