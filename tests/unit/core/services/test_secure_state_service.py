"""Tests for secure state service utilities."""

import pytest

from src.core.services.application_state_service import ApplicationStateService
from src.core.services.secure_state_service import SecureStateService, StateAccessProxy


class _DummyState:
    """Simple stand-in for FastAPI app.state."""


def test_state_access_proxy_allows_session_id_attribute() -> None:
    """Setting session_id should be allowed for middleware compatibility."""
    proxy = StateAccessProxy(_DummyState(), [])

    proxy.session_id = "abc123"

    assert proxy.session_id == "abc123"


def test_secure_state_service_access_log_is_bounded() -> None:
    """Access log should drop oldest entries to avoid unbounded growth."""
    app_state = ApplicationStateService()
    service = SecureStateService(app_state, max_access_log_entries=3)

    for i in range(5):
        service.update_command_prefix(f"/cmd{i}")

    access_log = service.get_access_log()

    assert len(access_log) == 3
    assert [entry["data"]["prefix"] for entry in access_log] == [
        "/cmd2",
        "/cmd3",
        "/cmd4",
    ]


def test_secure_state_service_rejects_invalid_log_size() -> None:
    """Constructor should guard against non-positive access log sizes."""
    app_state = ApplicationStateService()

    with pytest.raises(ValueError):
        SecureStateService(app_state, max_access_log_entries=0)
