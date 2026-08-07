"""Unit tests for SessionCancellationCoordinator."""

from __future__ import annotations

import pytest
from src.core.common.exceptions import SessionCancelledError
from src.core.domain.client_termination import (
    ClientTerminationReason,
)
from src.core.domain.session_key import SessionKey
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ICancellable,
)
from src.core.services.session_cancellation_coordinator import (
    SessionCancellationCoordinator,
)


class MockCancellable(ICancellable):
    """Mock cancellable for testing."""

    def __init__(self) -> None:
        """Initialize mock cancellable."""
        self.cancelled = False

    def cancel(self) -> None:
        """Mark as cancelled."""
        self.cancelled = True


@pytest.fixture
def coordinator() -> SessionCancellationCoordinator:
    """Create a SessionCancellationCoordinator instance."""
    # Use a short TTL for testing (0.1 second for faster tests)
    return SessionCancellationCoordinator(ttl_seconds=0.1)


@pytest.fixture
def http_session_key() -> SessionKey:
    """Create an HTTP session key."""
    return SessionKey(
        protocol="http", primary_id="trace-123", group_id="conversation-456"
    )


@pytest.fixture
def ws_session_key() -> SessionKey:
    """Create a WebSocket session key."""
    return SessionKey(protocol="ws", primary_id="ws:conn-789")


def test_is_cancelled_returns_false_for_new_session(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that is_cancelled returns False for a new session."""
    assert not coordinator.is_cancelled(http_session_key)


def test_cancel_session_marks_session_as_cancelled(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that cancel_session marks a session as cancelled."""
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )
    assert coordinator.is_cancelled(http_session_key)


def test_cancel_session_is_idempotent(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that calling cancel_session multiple times is idempotent."""
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_CANCELLED
    )
    # Should still be cancelled
    assert coordinator.is_cancelled(http_session_key)


def test_cancel_session_cancels_registered_work(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that cancel_session cancels all registered cancellables."""
    cancellable1 = MockCancellable()
    cancellable2 = MockCancellable()

    coordinator.register_cancellable(http_session_key, cancellable1)
    coordinator.register_cancellable(http_session_key, cancellable2)

    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    assert cancellable1.cancelled
    assert cancellable2.cancelled


def test_register_cancellable_after_cancellation_cancels_immediately(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that registering a cancellable after cancellation cancels it immediately."""
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    cancellable = MockCancellable()
    coordinator.register_cancellable(http_session_key, cancellable)

    assert cancellable.cancelled


def test_register_cancellable_before_cancellation_stores_for_later(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that registering a cancellable before cancellation stores it."""
    cancellable = MockCancellable()
    coordinator.register_cancellable(http_session_key, cancellable)

    assert not cancellable.cancelled

    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    assert cancellable.cancelled


def test_ensure_not_cancelled_passes_for_active_session(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that ensure_not_cancelled passes for an active session."""
    # Should not raise
    coordinator.ensure_not_cancelled(http_session_key)


def test_ensure_not_cancelled_raises_for_cancelled_session(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that ensure_not_cancelled raises for a cancelled session."""
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    with pytest.raises(SessionCancelledError) as exc_info:
        coordinator.ensure_not_cancelled(http_session_key)

    assert exc_info.value.session_key == http_session_key
    assert exc_info.value.reason == ClientTerminationReason.CLIENT_DISCONNECTED


def test_session_isolation_http_sessions(
    coordinator: SessionCancellationCoordinator,
) -> None:
    """Test that cancellation is isolated between different HTTP sessions."""
    session1 = SessionKey(protocol="http", primary_id="trace-1", group_id="conv-1")
    session2 = SessionKey(protocol="http", primary_id="trace-2", group_id="conv-1")

    coordinator.cancel_session(session1, ClientTerminationReason.CLIENT_DISCONNECTED)

    assert coordinator.is_cancelled(session1)
    assert not coordinator.is_cancelled(session2)


def test_session_isolation_ws_sessions(
    coordinator: SessionCancellationCoordinator,
) -> None:
    """Test that cancellation is isolated between different WebSocket sessions."""
    session1 = SessionKey(protocol="ws", primary_id="ws:conn-1")
    session2 = SessionKey(protocol="ws", primary_id="ws:conn-2")

    coordinator.cancel_session(session1, ClientTerminationReason.CLIENT_DISCONNECTED)

    assert coordinator.is_cancelled(session1)
    assert not coordinator.is_cancelled(session2)


def test_session_isolation_cross_protocol(
    coordinator: SessionCancellationCoordinator,
) -> None:
    """Test that cancellation is isolated between sessions with different protocols."""
    http_session = SessionKey(protocol="http", primary_id="trace-123")
    ws_session = SessionKey(protocol="ws", primary_id="ws:conn-123")

    coordinator.cancel_session(
        http_session, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    assert coordinator.is_cancelled(http_session)
    assert not coordinator.is_cancelled(ws_session)


def test_session_isolation_same_primary_id_different_group_id(
    coordinator: SessionCancellationCoordinator,
) -> None:
    """Test that cancellation is isolated by group_id when primary_id matches."""
    session1 = SessionKey(protocol="http", primary_id="trace-123", group_id="conv-1")
    session2 = SessionKey(protocol="http", primary_id="trace-123", group_id="conv-2")

    coordinator.cancel_session(session1, ClientTerminationReason.CLIENT_DISCONNECTED)

    assert coordinator.is_cancelled(session1)
    assert not coordinator.is_cancelled(session2)


def test_cleanup_removes_session_state(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that cleanup removes session state."""
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )
    assert coordinator.is_cancelled(http_session_key)

    coordinator.cleanup(http_session_key)

    assert not coordinator.is_cancelled(http_session_key)


def test_cleanup_is_idempotent(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that cleanup can be called multiple times safely."""
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )
    coordinator.cleanup(http_session_key)
    # Should not raise
    coordinator.cleanup(http_session_key)
    assert not coordinator.is_cancelled(http_session_key)


def test_cleanup_does_not_affect_other_sessions(
    coordinator: SessionCancellationCoordinator,
) -> None:
    """Test that cleanup only affects the specified session."""
    session1 = SessionKey(protocol="http", primary_id="trace-1")
    session2 = SessionKey(protocol="http", primary_id="trace-2")

    coordinator.cancel_session(session1, ClientTerminationReason.CLIENT_DISCONNECTED)
    coordinator.cancel_session(session2, ClientTerminationReason.CLIENT_DISCONNECTED)

    coordinator.cleanup(session1)

    assert not coordinator.is_cancelled(session1)
    assert coordinator.is_cancelled(session2)


def test_ttl_expiry_removes_old_sessions(
    coordinator: SessionCancellationCoordinator,
    http_session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that TTL expiry automatically removes old session state."""
    import time

    current_time = {"value": 1000.0}

    def fake_time() -> float:
        return current_time["value"]

    # Patch time.time globally - TTLCache uses it internally
    monkeypatch.setattr(time, "time", fake_time)
    # Also patch it in cachetools if it's imported there
    try:
        import cachetools

        if hasattr(cachetools, "time"):
            monkeypatch.setattr(cachetools.time, "time", fake_time)
    except Exception:
        pass

    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )
    assert coordinator.is_cancelled(http_session_key)

    # Advance time beyond TTL expiry (0.1 second in test fixture)
    current_time["value"] += 0.15

    # Accessing should trigger expiry check (TTLCache checks expiry on access)
    assert not coordinator.is_cancelled(http_session_key)


def test_multiple_cancellables_same_session(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that multiple cancellables can be registered for the same session."""
    cancellables = [MockCancellable() for _ in range(5)]

    for cancellable in cancellables:
        coordinator.register_cancellable(http_session_key, cancellable)

    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    assert all(c.cancelled for c in cancellables)


def test_cancellable_registration_after_cleanup(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that cancellables can be registered after cleanup."""
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )
    coordinator.cleanup(http_session_key)

    cancellable = MockCancellable()
    coordinator.register_cancellable(http_session_key, cancellable)

    # Should not be cancelled since session was cleaned up
    assert not cancellable.cancelled


def test_ensure_not_cancelled_includes_reason_in_exception(
    coordinator: SessionCancellationCoordinator, http_session_key: SessionKey
) -> None:
    """Test that ensure_not_cancelled includes reason in exception details."""
    coordinator.cancel_session(
        http_session_key, ClientTerminationReason.CLIENT_CANCELLED
    )

    with pytest.raises(SessionCancelledError) as exc_info:
        coordinator.ensure_not_cancelled(http_session_key)

    assert exc_info.value.reason == ClientTerminationReason.CLIENT_CANCELLED
    assert (
        exc_info.value.details["reason"]
        == ClientTerminationReason.CLIENT_CANCELLED.value
    )
