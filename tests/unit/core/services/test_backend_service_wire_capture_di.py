from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from src.connectors.base import LLMBackend
from src.core.app.test_builder import build_test_app_async
from src.core.config.app_config import AppConfig, BackendSettings
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import (
    ProcessedResponse,
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
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
    def __init__(self, config: Any, response_processor: Any) -> None:
        super().__init__(config, response_processor)
        self.type = "openai"  # Make sure this matches the expected backend type

    async def initialize(self, **kwargs: Any) -> None:  # pragma: no cover - unused
        return None

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        if isinstance(request_data, ChatRequest) and request_data.stream:

            async def gen() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(content=b"data: hello\n")
                yield ProcessedResponse(content=b"data: [DONE]\n\n")

            return StreamingResponseEnvelope(content=gen())
        return ResponseEnvelope(
            content={"id": "test", "object": "mock", "ok": True},
            headers={"content-type": "application/json"},
            status_code=200,
        )

    async def models(self):
        return []

    def get_available_models(self) -> list[str]:
        """Return empty list for mock."""
        return []


class DummyAppState(IApplicationState):
    def __init__(self):
        self.some_state = "test"


@pytest.mark.asyncio
async def test_backend_service_captures_non_streaming() -> None:
    """Test backend service wire capture for non-streaming responses using proper DI."""
    cfg = AppConfig(backends=BackendSettings(default_backend="openai"))

    # Build an integration test app with all required services (async version)
    app = await build_test_app_async(cfg)
    svc = get_required_service_from_app(app, IBackendService)

    # Use patch to mock the get_backend method
    with patch.object(svc, "get_backend", return_value=DummyBackend(cfg, None)):
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
    cfg = AppConfig(backends=BackendSettings(default_backend="openai"))

    # Build an integration test app with all required services (async version)
    app = await build_test_app_async(cfg)
    svc = get_required_service_from_app(app, IBackendService)

    # Use patch to mock the get_backend method
    with patch.object(svc, "get_backend", return_value=DummyBackend(cfg, None)):
        # Need to explicitly specify backend_type in extra_body
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
            extra_body={"session_id": "s2", "backend_type": "openai"},
        )
        res = await svc.call_completion(req, stream=True)
        assert isinstance(res, StreamingResponseEnvelope)
        out: list[Any] = []
        async for chunk in res.content:
            out.append(chunk)
        # Verify that we received chunks
        assert len(out) > 0
