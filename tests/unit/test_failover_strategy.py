from typing import Any

from src.core.services.failover_service import FailoverAttempt
from src.core.services.failover_strategy import DefaultFailoverStrategy


class FakeCoordinator:
    def __init__(self, attempts: list[FailoverAttempt]) -> None:
        self._attempts = attempts

    def get_failover_attempts(
        self, model: str, backend_type: str
    ) -> list[FailoverAttempt]:
        # ignore inputs in this fake; return preconfigured attempts
        return self._attempts

    def register_route(
        self, model: str, route: dict[str, Any]
    ) -> None:  # pragma: no cover - not used here
        pass


def test_default_failover_strategy_maps_attempts() -> None:
    attempts = [
        FailoverAttempt(backend="openai", model="gpt-4o"),
        FailoverAttempt(backend="openrouter", model="meta/llama-3.1"),
    ]
    strategy = DefaultFailoverStrategy(FakeCoordinator(attempts))
    plan = strategy.get_failover_plan(model="unused", backend_type="unused")
    assert plan == [("openai", "gpt-4o"), ("openrouter", "meta/llama-3.1")]
