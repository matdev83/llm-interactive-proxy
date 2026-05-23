"""Tests for BackendCompletionFlow rate limit feedback behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget
from src.core.interfaces.resilience_interface import ResilienceDecision

from tests.unit.core.services.backend_flow_test_helper import (
    create_test_backend_completion_flow,
)


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
    """BackendCompletionFlow should record failure via ResilienceCoordinator on 429."""
    app_config = AppConfig()

    # Mock ResilienceCoordinator to track failure recording
    mock_resilience = MagicMock()
    mock_decision = MagicMock(spec=ResilienceDecision)
    mock_decision.should_proceed.return_value = True  # Allow the request to proceed
    mock_resilience.check_availability.return_value = mock_decision
    mock_resilience.record_failure = MagicMock()

    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    backend_lifecycle_manager.get_active_backends.return_value = {}

    backend_factory = MagicMock()

    config = MagicMock(spec=AppConfig)
    config.backends = MagicMock()
    config.backends.get.return_value = None
    config.identity = None

    deps = {
        "backend_model_resolver": MagicMock(),
        "stream_session_id_resolver": MagicMock(),
        "failover_planner": MagicMock(),
        "session_service": MagicMock(),
        "backend_lifecycle_manager": backend_lifecycle_manager,
        "backend_config_service": MagicMock(),
        "reasoning_config_applicator": MagicMock(),
        "uri_parameter_applicator": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "usage_tracking_wrapper": MagicMock(),
        "exception_normalizer": MagicMock(),
        "planning_phase_manager": MagicMock(),
        "backend_factory": backend_factory,
        "config": config,
        "app_state": MagicMock(),
        "failover_coordinator": MagicMock(),
        "failure_handling_strategy": None,  # No strategy means surface error
        "resilience_coordinator": mock_resilience,
    }

    backend = _DummyBackend(app_config)

    # Defaults
    deps["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=ResolvedTarget(
            backend=backend.backend_type, model="gemini-2.5-pro", uri_params={}
        )
    )
    deps["backend_model_resolver"].synchronize_request_with_target = Mock(
        side_effect=lambda r, t: r
    )
    deps["reasoning_config_applicator"].apply = Mock(side_effect=lambda r, s: r)
    deps["uri_parameter_applicator"].apply = Mock(side_effect=lambda r, u, b, s: r)

    def normalize_side_effect(exc, backend_type):
        if getattr(exc, "status_code", None) == 429:
            return RateLimitExceededError("Rate limit exceeded")
        return exc

    deps["exception_normalizer"].normalize = Mock(side_effect=normalize_side_effect)

    deps["backend_lifecycle_manager"].get_or_create = AsyncMock(return_value=backend)

    flow = create_test_backend_completion_flow(deps)

    request = ChatRequest(
        model="gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # With allow_failover=False, 429 should raise immediately
    with pytest.raises((BackendError, RateLimitExceededError)):
        await flow.call_completion(request, allow_failover=False)

    # Only one call should have been made (no automatic retry without failover)
    assert backend._calls == 1
    # Verify failure was recorded in resilience coordinator
    mock_resilience.record_failure.assert_called_once()
