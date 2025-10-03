"""Tests for secure state service utilities."""

from src.core.services.secure_state_service import StateAccessProxy


class _DummyState:
    """Simple stand-in for FastAPI app.state."""


def test_state_access_proxy_allows_session_id_attribute() -> None:
    """Setting session_id should be allowed for middleware compatibility."""
    proxy = StateAccessProxy(_DummyState(), [])

    proxy.session_id = "abc123"

    assert proxy.session_id == "abc123"
