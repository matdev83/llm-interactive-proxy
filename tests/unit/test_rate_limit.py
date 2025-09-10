import time
from typing import Any

from src.rate_limit import RateLimitRegistry, parse_retry_delay


def test_parse_retry_delay_with_prefixed_string() -> None:
    detail: str = (
        '429 Too Many Requests. {"error": {"details": ['
        '{"@type": "type.googleapis.com/google.rpc.RetryInfo",'
        ' "retryDelay": "29s"}]}}"'
    )
    assert parse_retry_delay(detail) == 29.0


def test_rate_limit_registry_earliest(monkeypatch: Any) -> None:
    t: float = 0.0
    monkeypatch.setattr(time, "time", lambda: t)
    registry = RateLimitRegistry()
    registry.set("b1", "m1", "k1", 5)
    registry.set("b2", "m1", "k2", 2)
    assert registry.earliest() == 2
    t = 3
    monkeypatch.setattr(time, "time", lambda: t)
    assert registry.get("b2", "m1", "k2") is None
    assert registry.earliest() == 5
