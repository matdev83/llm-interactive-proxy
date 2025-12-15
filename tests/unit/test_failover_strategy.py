from unittest.mock import Mock

from src.core.services.failover_service import FailoverAttempt
from src.core.services.failover_strategy import DefaultFailoverStrategy


def test_default_failover_strategy_maps_attempts() -> None:
    attempts = [
        FailoverAttempt(backend="openai", model="gpt-4o"),
        FailoverAttempt(backend="openrouter", model="meta/llama-3.1"),
    ]

    # Use a Mock instead of a custom Fake class to avoid potential test collection issues
    # and to make the test more standard.
    coordinator = Mock()
    coordinator.get_failover_attempts.return_value = attempts

    strategy = DefaultFailoverStrategy(coordinator)
    plan = strategy.get_failover_plan(model="unused", backend_type="unused")

    assert plan == [("openai", "gpt-4o"), ("openrouter", "meta/llama-3.1")]
    coordinator.get_failover_attempts.assert_called_once_with("unused", "unused")
