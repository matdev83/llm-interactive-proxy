"""Tests for BackendService rate limit feedback behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.rate_limiter_interface import RateLimitInfo
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService


class _DummyBackend(LLMBackend):
    """Backend that fails with a 429 once before succeeding."""

    backend_type = "gemini-oauth-plan"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._calls = 0

    async def initialize(self, **kwargs) -> None:  # pragma: no cover - unused
        return None

    async def chat_completions(
        self,
        request_data,
        processed_messages,
        effective_model: str,
        identity=None,
        **kwargs,
    ):
        self._calls += 1
        if self._calls == 1:
            raise BackendError(
                message="Rate limit exceeded",
                backend_name=self.backend_type,
                details={
                    "error": {
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                "retryDelay": "5s",
                            }
                        ]
                    }
                },
                status_code=429,
                code="rate_limit_exceeded",
            )
        return ResponseEnvelope(content={"message": "ok"})

    def get_available_models(self) -> list[str]:
        """Return empty list for mock."""
        return []


@pytest.mark.asyncio
async def test_call_completion_applies_cooldown_on_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BackendService should push cooldown feedback to the rate limiter when a backend returns 429."""

    app_config = AppConfig()
    rate_limiter = AsyncMock()
    rate_limiter.check_limit.return_value = RateLimitInfo(
        is_limited=False, remaining=10, reset_at=None, limit=60, time_window=60
    )
    rate_limiter.record_usage.return_value = None
    rate_limiter.apply_cooldown = AsyncMock()

    factory = MagicMock(spec=BackendFactory)
    session_service = AsyncMock(spec=ISessionService)
    session_service.get_session.return_value = None
    app_state = MagicMock(spec=IApplicationState)

    service = BackendService(
        factory=factory,
        rate_limiter=rate_limiter,
        config=app_config,
        session_service=session_service,
        app_state=app_state,
        backend_config_provider=None,
        failover_routes=None,
        failover_strategy=None,
        failover_coordinator=None,
        wire_capture=None,
    )

    backend = _DummyBackend(app_config)
    service._get_or_create_backend = AsyncMock(return_value=backend)
    service._resolve_backend_and_model = AsyncMock(
        return_value=(
            backend.backend_type,
            "gemini-cli-oauth-personal:models/gemini-2.5-pro",
            {},  # uri_params
        )
    )

    sleep_mock = AsyncMock()
    monkeypatch.setattr("src.core.services.backend_service.asyncio.sleep", sleep_mock)

    request = ChatRequest(
        model="gemini-cli-oauth-personal:models/gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    response = await service.call_completion(request)

    assert isinstance(response, ResponseEnvelope)
    assert backend._calls == 2  # initial failure + retry after cooldown
    rate_limiter.apply_cooldown.assert_awaited_once_with("backend:gemini-oauth-plan", 5)
    sleep_mock.assert_awaited_once_with(5)
