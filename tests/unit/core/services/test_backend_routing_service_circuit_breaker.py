"""Integration tests for circuit breaker and health-gated backend routing."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import src.core.services.resilience.circuit_breaker_state as circuit_breaker_state_module
from src.core.common.exceptions import RoutingError, ServiceUnavailableError
from src.core.config.app_config import BackendConfig, RoutingConfig
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.resilience_interface import ActionType
from src.core.services.backend_completion_flow.availability_checker import (
    BackendAvailabilityChecker,
)
from src.core.services.backend_routing_service import BackendRoutingService
from src.core.services.health.endpoint_registry import EndpointRegistry
from src.core.services.provider_error_classifier import ProviderErrorClassifier
from src.core.services.resilience.circuit_breaker_state import (
    CircuitBreakerConfig,
    CircuitBreakerStateManager,
)
from src.core.services.resilience.coordinator import ResilienceCoordinator
from src.core.services.resilience.handlers import (
    AuthErrorHandler,
    CircuitBreakerErrorHandler,
    RateLimitErrorHandler,
)
from src.core.services.resilience.rate_limit_state import RateLimitStateManager


class _FakeClock:
    def __init__(self) -> None:
        self._now = 1000.0

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(circuit_breaker_state_module.time, "monotonic", clock.monotonic)
    return clock


@pytest.fixture
def mock_config_provider() -> Mock:
    provider = Mock()
    configs: dict[str, BackendConfig] = {
        "openai.1": BackendConfig(api_key="k1", models=["gpt-4"]),
        "openai.2": BackendConfig(api_key="k2", models=["gpt-4"]),
    }
    provider.configs = configs

    def get_config(name: str) -> BackendConfig | None:
        return configs.get(name)

    def iter_names() -> list[str]:
        return list(configs.keys())

    provider.get_backend_config.side_effect = get_config
    provider.iter_backend_names.side_effect = iter_names
    return provider


def _build_resilience_coordinator(
    *,
    circuit_breaker_config: CircuitBreakerConfig,
    endpoint_registry: EndpointRegistry | None = None,
    health_gating_enabled: bool = False,
) -> tuple[ResilienceCoordinator, CircuitBreakerStateManager]:
    rate_limit_state = RateLimitStateManager()
    circuit_breaker_state = CircuitBreakerStateManager(config=circuit_breaker_config)

    auth_handler = AuthErrorHandler(rate_limit_state)
    rate_limit_handler = RateLimitErrorHandler(
        rate_limit_state, next_handler=auth_handler
    )
    circuit_breaker_handler = CircuitBreakerErrorHandler(
        circuit_breaker_state,
        next_handler=rate_limit_handler,
    )

    coordinator = ResilienceCoordinator(
        state_manager=rate_limit_state,
        provider_error_classifier=ProviderErrorClassifier(),
        error_handler_chain=circuit_breaker_handler,
        circuit_breaker_state=circuit_breaker_state,
        endpoint_registry=endpoint_registry,
        health_gating_enabled=health_gating_enabled,
    )
    return coordinator, circuit_breaker_state


def test_model_routing_excludes_open_circuit_candidate(
    mock_config_provider: Mock,
) -> None:
    coordinator, circuit_breaker_state = _build_resilience_coordinator(
        circuit_breaker_config=CircuitBreakerConfig(
            failure_threshold=1,
            open_cooldown_seconds=30.0,
        ),
    )
    circuit_breaker_state.record_failure("openai.1", reason="http_500")

    service = BackendRoutingService(
        mock_config_provider,
        RoutingConfig(),
        resilience_coordinator=coordinator,
    )

    assert service.resolve_model_only_backend("gpt-4") == "openai.2"


def test_model_routing_raises_temporarily_unavailable_when_all_candidates_filtered(
    mock_config_provider: Mock,
) -> None:
    endpoint_registry = EndpointRegistry()
    health_state = endpoint_registry.register_backend(
        "openai.2",
        "https://api.openai-two.example/v1",
    )
    health_state.record_http_failure("endpoint unavailable", failure_threshold=1)

    coordinator, circuit_breaker_state = _build_resilience_coordinator(
        circuit_breaker_config=CircuitBreakerConfig(
            failure_threshold=1,
            open_cooldown_seconds=30.0,
        ),
        endpoint_registry=endpoint_registry,
        health_gating_enabled=True,
    )
    circuit_breaker_state.record_failure("openai.1", reason="timeout")

    service = BackendRoutingService(
        mock_config_provider,
        RoutingConfig(),
        resilience_coordinator=coordinator,
    )

    with pytest.raises(RoutingError) as exc:
        service.resolve_model_only_backend("gpt-4")

    assert exc.value.details is not None
    assert exc.value.details.get("code") == "temporarily_unavailable"
    assert sorted(exc.value.details.get("candidates", [])) == ["openai.1", "openai.2"]


def test_coordinator_rejects_unhealthy_endpoint_for_scoped_instance() -> None:
    endpoint_registry = EndpointRegistry()
    health_state = endpoint_registry.register_backend(
        "openai-codex.1",
        "https://api.openai-codex.example/v1",
    )
    health_state.record_http_failure("gateway timeout", failure_threshold=1)

    coordinator, _ = _build_resilience_coordinator(
        circuit_breaker_config=CircuitBreakerConfig(),
        endpoint_registry=endpoint_registry,
        health_gating_enabled=True,
    )

    decision = coordinator.check_availability("openai-codex.1:session-123", "gpt-4")

    assert decision.action == ActionType.REJECT
    assert decision.should_proceed() is False
    assert "unhealthy" in decision.reason


@pytest.mark.asyncio
async def test_availability_checker_maps_circuit_open_and_endpoint_unhealthy_to_service_unavailable(
    fake_clock: _FakeClock,
) -> None:
    lifecycle_manager = Mock(spec=IBackendLifecycleManager)
    lifecycle_manager.get_disabled_backends.return_value = {}

    coordinator, circuit_breaker_state = _build_resilience_coordinator(
        circuit_breaker_config=CircuitBreakerConfig(
            failure_threshold=1,
            open_cooldown_seconds=20.0,
        ),
    )
    circuit_breaker_state.record_failure("openai.1", reason="http_500")
    checker = BackendAvailabilityChecker(
        backend_lifecycle_manager=lifecycle_manager,
        resilience_coordinator=coordinator,
        failover_routes={},
    )

    with pytest.raises(ServiceUnavailableError) as circuit_exc:
        await checker.check_backend_availability(
            backend_type="openai.1",
            effective_model="gpt-4",
            allow_failover=True,
        )

    assert circuit_exc.value.details.get("retry_after_seconds", 0) > 0
    assert circuit_exc.value.details.get("cooldown_remaining", 0) > 0

    endpoint_registry = EndpointRegistry()
    health_state = endpoint_registry.register_backend(
        "openai.2",
        "https://api.openai-two.example/v1",
    )
    health_state.record_http_failure("endpoint unavailable", failure_threshold=1)
    unhealthy_coordinator, _ = _build_resilience_coordinator(
        circuit_breaker_config=CircuitBreakerConfig(),
        endpoint_registry=endpoint_registry,
        health_gating_enabled=True,
    )
    unhealthy_checker = BackendAvailabilityChecker(
        backend_lifecycle_manager=lifecycle_manager,
        resilience_coordinator=unhealthy_coordinator,
        failover_routes={},
    )

    with pytest.raises(ServiceUnavailableError) as unhealthy_exc:
        await unhealthy_checker.check_backend_availability(
            backend_type="openai.2",
            effective_model="gpt-4",
            allow_failover=True,
        )

    assert unhealthy_exc.value.details.get("reason") == "endpoint_unhealthy"


@pytest.mark.asyncio
async def test_routing_precheck_does_not_consume_half_open_probe_capacity(
    fake_clock: _FakeClock,
    mock_config_provider: Mock,
) -> None:
    lifecycle_manager = Mock(spec=IBackendLifecycleManager)
    lifecycle_manager.get_disabled_backends.return_value = {}

    coordinator, _ = _build_resilience_coordinator(
        circuit_breaker_config=CircuitBreakerConfig(
            failure_threshold=1,
            open_cooldown_seconds=5.0,
            half_open_max_inflight=1,
        ),
    )
    checker = BackendAvailabilityChecker(
        backend_lifecycle_manager=lifecycle_manager,
        resilience_coordinator=coordinator,
        failover_routes={},
    )
    service = BackendRoutingService(
        mock_config_provider,
        RoutingConfig(),
        resilience_coordinator=coordinator,
    )

    error = TimeoutError("upstream timeout")
    coordinator.record_failure("openai.1", "gpt-4", error)
    assert coordinator.check_availability("openai.1", "gpt-4").should_proceed() is False

    fake_clock.advance(5.1)
    assert service.resolve_model_only_backend("gpt-4") == "openai.1"

    await checker.check_backend_availability(
        backend_type="openai.1",
        effective_model="gpt-4",
        allow_failover=True,
    )
    with pytest.raises(RoutingError) as exc_info:
        await checker.check_backend_availability(
            backend_type="openai.1",
            effective_model="gpt-4",
            allow_failover=True,
        )
    assert exc_info.value.details is not None
    assert exc_info.value.details.get("reason") == "half_open_probe_inflight"


def test_coordinator_record_success_closes_half_open_circuit_and_resets_counters(
    fake_clock: _FakeClock,
) -> None:
    coordinator, _ = _build_resilience_coordinator(
        circuit_breaker_config=CircuitBreakerConfig(
            failure_threshold=2,
            open_cooldown_seconds=10.0,
            half_open_success_threshold=1,
            half_open_max_inflight=1,
        ),
    )
    error = TimeoutError("upstream timeout")

    coordinator.record_failure("openai.1", "gpt-4", error)
    coordinator.record_failure("openai.1", "gpt-4", error)
    rejected = coordinator.check_availability("openai.1", "gpt-4")
    assert rejected.should_proceed() is False
    assert rejected.cooldown_remaining is not None

    fake_clock.advance(10.1)
    probe_decision = coordinator.check_availability("openai.1", "gpt-4")
    assert probe_decision.should_proceed() is True
    second_probe = coordinator.check_availability("openai.1", "gpt-4")
    assert second_probe.should_proceed() is True
    assert coordinator.try_acquire_circuit_breaker_probe("openai.1") is True
    assert coordinator.try_acquire_circuit_breaker_probe("openai.1") is False
    constrained_probe = coordinator.check_availability("openai.1", "gpt-4")
    assert constrained_probe.should_proceed() is False
    assert constrained_probe.reason == "half_open_probe_inflight"

    coordinator.record_success("openai.1", "gpt-4")
    assert coordinator.check_availability("openai.1", "gpt-4").should_proceed() is True

    coordinator.record_failure("openai.1", "gpt-4", error)
    assert coordinator.check_availability("openai.1", "gpt-4").should_proceed() is True
