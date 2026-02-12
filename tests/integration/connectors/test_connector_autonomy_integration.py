from __future__ import annotations

from typing import cast

from src.core.common.exceptions import RateLimitExceededError
from src.core.config.app_config import BackendConfig, RoutingConfig
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    FailureHandlingConfig,
)
from src.core.services.backend_routing_service import BackendRoutingService
from src.core.services.failure_handling_strategy import DefaultFailureHandlingStrategy


class _StaticConfigProvider:
    def __init__(self) -> None:
        self._configs = {
            "gemini-oauth-auto.1": BackendConfig(
                api_key="k1", models=["gemini-2.5-pro"]
            ),
            "gemini-oauth-auto.2": BackendConfig(
                api_key="k2", models=["gemini-2.5-pro"]
            ),
            "openai.1": BackendConfig(api_key="o1", models=["gpt-4o"]),
            "openai.2": BackendConfig(api_key="o2", models=["gpt-4o"]),
        }

    def iter_backend_names(self):
        return self._configs.keys()

    def get_backend_config(self, name: str):
        return self._configs.get(name)


def test_constrained_connector_family_keeps_proxy_selection_stable() -> None:
    """Proxy should not round-robin constrained connector families."""
    provider = cast(IBackendConfigProvider, _StaticConfigProvider())
    routing_config = RoutingConfig().model_copy(
        update={"constrained_backend_families": ["gemini-oauth-auto*"]}
    )
    service = BackendRoutingService(
        provider,
        routing_config,
    )

    resolved = {service.resolve_model_only_backend("gemini-2.5-pro") for _ in range(20)}
    assert resolved == {"gemini-oauth-auto.1"}


def test_unconstrained_connector_family_allows_round_robin() -> None:
    """Unconstrained connector families still use proxy-level round-robin."""
    provider = cast(IBackendConfigProvider, _StaticConfigProvider())
    service = BackendRoutingService(provider, RoutingConfig())

    resolved = {service.resolve_model_only_backend("gpt-4o") for _ in range(20)}
    assert resolved == {"openai.1", "openai.2"}


def test_proxy_prefers_failover_over_long_connector_hold_windows() -> None:
    """Proxy-level boundaries should preempt long connector wait/hold windows."""
    strategy = DefaultFailureHandlingStrategy(
        config=FailureHandlingConfig(
            max_silent_wait=30.0,
            total_timeout_budget=4.0,
            max_failover_hops=5,
            min_retry_wait=0.1,
        )
    )
    error = RateLimitExceededError(
        message="connector-level hold suggested",
        backend_name="gemini-oauth-auto.1",
        details={"retry_after": 15.0},
    )

    decision = strategy.decide(
        error=error,
        model="gemini-2.5-pro",
        current_backend="gemini-oauth-auto.1",
        attempted_backends=[],
        elapsed_time=1.0,
        is_streaming=False,
        content_started=False,
        available_backends=["gemini-oauth-auto.2"],
    )

    assert decision.decision == FailureDecision.FAILOVER_IMMEDIATE
    assert decision.next_backend == "gemini-oauth-auto.2"


def test_proxy_attempt_budget_wins_over_retry_wait_hints() -> None:
    """Attempt budget exhaustion should surface deterministically."""
    strategy = DefaultFailureHandlingStrategy(
        config=FailureHandlingConfig(
            max_silent_wait=30.0,
            total_timeout_budget=2.0,
            max_failover_hops=2,
            min_retry_wait=0.1,
        )
    )
    error = RateLimitExceededError(
        message="retry-after available",
        backend_name="gemini-oauth-auto.1",
        details={"retry_after": 0.2},
    )

    decision = strategy.decide(
        error=error,
        model="gemini-2.5-pro",
        current_backend="gemini-oauth-auto.1",
        attempted_backends=["gemini-oauth-auto.1", "gemini-oauth-auto.2"],
        elapsed_time=2.1,
        is_streaming=False,
        content_started=False,
        available_backends=["gemini-oauth-auto.2"],
    )

    assert decision.decision == FailureDecision.SURFACE_ERROR
    assert decision.error_to_surface is not None
