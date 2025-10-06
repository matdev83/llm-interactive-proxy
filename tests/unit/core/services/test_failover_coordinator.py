from __future__ import annotations

from src.core.services.failover_coordinator import FailoverCoordinator
from src.core.services.failover_service import FailoverAttempt, FailoverService


def test_coordinator_handles_simple_backend_mapping() -> None:
    service = FailoverService({"openai": "anthropic"})
    coordinator = FailoverCoordinator(service)

    attempts = coordinator.get_failover_attempts("gpt-4o", "openai")

    assert attempts == [FailoverAttempt(backend="anthropic", model="gpt-4o")]


def test_coordinator_normalizes_structured_routes() -> None:
    service = FailoverService(
        {"openai": {"policy": "k", "elements": ["openrouter:meta/llama-3"]}}
    )
    coordinator = FailoverCoordinator(service)

    attempts = coordinator.get_failover_attempts("gpt-4o", "openai")

    assert attempts == [FailoverAttempt(backend="openrouter", model="meta/llama-3")]
