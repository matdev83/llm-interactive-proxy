import pytest
from src.rate_limit import RateLimitRegistry


def test_next_available(monkeypatch):
    reg = RateLimitRegistry()

    monkeypatch.setattr('src.rate_limit.time.time', lambda: 0)
    reg.set('b1', 'm1', 'k1', 5)
    reg.set('b2', 'm2', 'k2', 2)

    monkeypatch.setattr('src.rate_limit.time.time', lambda: 1)
    assert reg.next_available() == pytest.approx(2)

    monkeypatch.setattr('src.rate_limit.time.time', lambda: 3)
    assert reg.next_available() == pytest.approx(5)

    monkeypatch.setattr('src.rate_limit.time.time', lambda: 6)
    assert reg.next_available() is None
