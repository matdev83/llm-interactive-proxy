"""Tests for BackendService rate limit feedback behavior.

Note: With the new failure handling architecture, rate limiting feedback
goes to the ResilienceCoordinator rather than the legacy RateLimiter.
Retry decisions are made by the IFailureHandlingStrategy.

NOTE: These tests need refactoring after Phase 4 of backend-service-god-object-refactoring.
BackendService is now a thin facade. The test mocks internal methods like
_backend_lifecycle_manager.get_or_create and _resolve_backend_and_model that no longer
exist on BackendService. The logic has been moved to BackendCompletionFlow and other
collaborators. Tests need to be refactored to test the new architecture.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.rate_limiter_interface import RateLimitInfo
from src.core.interfaces.resilience_interface import ResilienceDecision
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory


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


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - internal methods moved to collaborators"
)
@pytest.mark.asyncio
async def test_call_completion_applies_cooldown_on_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BackendService should record failure via ResilienceCoordinator on 429.

    Note: With the new architecture, 429 errors with allow_failover=False
    are raised immediately. The ResilienceCoordinator records the failure.
    This test verifies the failure is recorded for cooldown tracking.
    """
    app_config = AppConfig()
    rate_limiter = AsyncMock()
    rate_limiter.check_limit.return_value = RateLimitInfo(
        is_limited=False, remaining=10, reset_at=None, limit=60, time_window=60
    )
    rate_limiter.record_usage.return_value = None
    rate_limiter.apply_cooldown = AsyncMock()

    # Mock ResilienceCoordinator to track failure recording
    mock_resilience = MagicMock()
    mock_decision = MagicMock(spec=ResilienceDecision)
    mock_decision.should_proceed.return_value = True  # Allow the request to proceed
    mock_resilience.check_availability.return_value = mock_decision
    mock_resilience.record_failure = MagicMock()

    factory = MagicMock(spec=BackendFactory)
    session_service = AsyncMock(spec=ISessionService)
    session_service.get_session.return_value = None
    app_state = MagicMock(spec=IApplicationState)

    from tests.unit.fixtures.backend_service_builder import (
        create_backend_service_with_mocks,
    )

    service = create_backend_service_with_mocks(
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
        resilience_coordinator=mock_resilience,
    )

    backend = _DummyBackend(app_config)
    service._backend_lifecycle_manager.get_or_create = AsyncMock(return_value=backend)
    service._resolve_backend_and_model = AsyncMock(
        return_value=(
            backend.backend_type,
            "gemini-cli-oauth-personal:models/gemini-2.5-pro",
            {},  # uri_params
        )
    )

    request = ChatRequest(
        model="gemini-cli-oauth-personal:models/gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # With allow_failover=False, 429 should raise immediately
    with pytest.raises((BackendError, RateLimitExceededError)):
        await service.call_completion(request, allow_failover=False)

    # Only one call should have been made (no automatic retry without failover)
    assert backend._calls == 1
    # Verify failure was recorded in resilience coordinator
    mock_resilience.record_failure.assert_called_once()
