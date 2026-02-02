from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest
from src.core.interfaces.notification_service_interface import INotificationService
from src.core.services.angel_service import AngelService, _model_health


class MockNotificationService(INotificationService):
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self._enabled = True

    async def send_notification(self, title: str, message: str) -> str | None:
        self.notifications.append((title, message))
        return "notif-id"

    @property
    def is_enabled(self) -> bool:
        return self._enabled


@pytest.fixture
def clean_health() -> None:
    """Clear global health state before/after tests."""
    with _model_health_lock_context():
        _model_health.clear()
    yield
    with _model_health_lock_context():
        _model_health.clear()


def _model_health_lock_context():
    from src.core.services.angel_service import _health_lock
    return _health_lock


@pytest.mark.asyncio
async def test_circuit_breaker_trips_after_max_failures(clean_health: Any) -> None:
    model_spec = "test:model"
    notif_svc = MockNotificationService()
    svc = AngelService(
        model_spec=model_spec,
        max_consecutive_failures=3,
        cooldown_seconds=60,
        notification_service=notif_svc,
    )

    # Initially healthy
    assert svc.is_healthy() is True

    # 1st failure
    await svc.report_failure()
    assert svc.is_healthy() is True

    # 2nd failure
    await svc.report_failure()
    assert svc.is_healthy() is True

    # 3rd failure - should trip
    await svc.report_failure()
    assert svc.is_healthy() is False

    # Check notification (fire-and-forget, give it a tiny bit of time)
    await asyncio.sleep(0.01)
    assert len(notif_svc.notifications) == 1
    assert "Angel Verification Disabled" in notif_svc.notifications[0][0]


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_success(clean_health: Any) -> None:
    model_spec = "test:model"
    svc = AngelService(
        model_spec=model_spec,
        max_consecutive_failures=3,
    )

    # 2 failures
    await svc.report_failure()
    await svc.report_failure()
    assert svc.is_healthy() is True

    # Success should reset counter
    await svc.report_success()
    
    # Needs 3 more failures to trip
    await svc.report_failure()
    await svc.report_failure()
    assert svc.is_healthy() is True
    await svc.report_failure()
    assert svc.is_healthy() is False


@pytest.mark.asyncio
async def test_circuit_breaker_cooldown_expiry(clean_health: Any) -> None:
    model_spec = "test:model"
    # Use very short cooldown
    svc = AngelService(
        model_spec=model_spec,
        max_consecutive_failures=1,
        cooldown_seconds=1,
    )

    await svc.report_failure()
    assert svc.is_healthy() is False

    # Mock time passage by modifying the health record
    from src.core.services.angel_service import _health_lock
    with _health_lock:
        _model_health[model_spec].unhealthy_until = datetime.now() - timedelta(seconds=1)

    # Should be healthy again
    assert svc.is_healthy() is True


@pytest.mark.asyncio
async def test_circuit_breaker_disabled_when_angel_disabled(clean_health: Any) -> None:
    svc = AngelService(model_spec=None)
    assert svc.is_enabled() is False
    assert svc.is_healthy() is False  # is_healthy returns False if disabled

    await svc.report_failure()
    # Should not crash or record anything in global state for empty spec
    assert len(_model_health) == 0
